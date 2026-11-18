from fastapi.testclient import TestClient

from app.errors import ModelInvalidOutputError, ModelTimeoutError
from app.main import create_app
from app.model.base import BaseModelClient
from app.schemas import DiffItem, ModelAnalysis, QuoteOut
from tests.conftest import make_settings
from tests.fixtures import (
    LIBRARY_ARTICLE,
    LIBRARY_SENTENCES,
    evidence_of,
    library_payload,
    unknown_payload,
)

ANALYZE = "/api/v1/reviews/analyze"


class FakeClient(BaseModelClient):
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    async def analyze(self, req, evidence):
        if self._exc:
            raise self._exc
        return self._result


def fake_analysis(**overrides) -> ModelAnalysis:
    base = dict(
        differences=[DiffItem(kind="added", detail_zh="测试用差异说明")],
        quotes=[],
        explanation_zh="测试用解释",
        follow_up_zh="测试用追问",
        issue_types=[],
        supported_option=None,
        definitive=True,
    )
    base.update(overrides)
    return ModelAnalysis(**base)


def assert_quotes_locatable(article: str, quotes: list):
    for q in quotes:
        assert article[q["start"]:q["end"]] == q["text"]


def test_healthz_mock(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["model_backend"] == "mock"
    assert body["model_configured"] is True


def test_library_correct_vs_wrong_evidence_different_followup(client):
    """同选 B：圈第二句（对句）与圈第一句（错句）应得到不同追问。"""
    r2 = client.post(ANALYZE, json=library_payload(
        evidence=[evidence_of(LIBRARY_ARTICLE, LIBRARY_SENTENCES[1])]))
    r1 = client.post(ANALYZE, json=library_payload(
        evidence=[evidence_of(LIBRARY_ARTICLE, LIBRARY_SENTENCES[0])]))
    assert r2.status_code == r1.status_code == 200
    b2, b1 = r2.json(), r1.json()
    assert b2["status"] == b1["status"] == "ok"
    f2, f1 = b2["review"]["follow_up_zh"], b1["review"]["follow_up_zh"]
    assert f2 != f1
    assert LIBRARY_SENTENCES[1][:40] in f2
    assert LIBRARY_SENTENCES[0][:40] in f1
    assert_quotes_locatable(LIBRARY_ARTICLE, b2["review"]["quotes"])
    assert_quotes_locatable(LIBRARY_ARTICLE, b1["review"]["quotes"])
    assert b2["review"]["advisory"] == "suggestion"
    assert "scope" in b2["review"]["issue_types"]


def test_missing_reference_answer_still_analyzes(client):
    resp = client.post(ANALYZE, json=library_payload(
        reference_answer=None, reference_explanation=None))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["review"]["differences"]
    assert body["review"]["follow_up_zh"]


def test_fabricated_quote_marks_needs_review(app, client):
    app.state.model_client = FakeClient(result=fake_analysis(
        quotes=[QuoteOut(text="This sentence was invented by the model and is not in the article.")]))
    resp = client.post(ANALYZE, json=library_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "needs_review"
    codes = [r["code"] for r in body["review"]["needs_review_reasons"]]
    assert "QUOTE_NOT_LOCATABLE" in codes
    assert body["review"]["quotes"] == []


def test_reference_conflict_marks_needs_review(app, client):
    app.state.model_client = FakeClient(result=fake_analysis(supported_option="B"))
    resp = client.post(ANALYZE, json=library_payload())  # reference_answer=D
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "needs_review"
    codes = [r["code"] for r in body["review"]["needs_review_reasons"]]
    assert "REFERENCE_CONFLICT" in codes


def test_model_timeout_returns_identifiable_error(app, client):
    app.state.model_client = FakeClient(exc=ModelTimeoutError())
    resp = client.post(ANALYZE, json=library_payload())
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "MODEL_TIMEOUT"
    assert "手动复盘" in body["error"]["message_zh"]


def test_model_invalid_output_returns_identifiable_error(app, client):
    app.state.model_client = FakeClient(exc=ModelInvalidOutputError())
    resp = client.post(ANALYZE, json=library_payload())
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "MODEL_INVALID_OUTPUT"


def test_model_not_configured_healthz_still_ok():
    app = create_app(make_settings(model_backend="openai"))
    with TestClient(app) as c:
        health = c.get("/healthz")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["model_configured"] is False
        resp = c.post(ANALYZE, json=library_payload())
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == "MODEL_NOT_CONFIGURED"
        assert "手动复盘" in body["error"]["message_zh"]


def test_unknown_article_not_hardcoded(client):
    """陌生文章（因果题）：逻辑不依赖图书馆样例。"""
    resp = client.post(ANALYZE, json=unknown_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    review = body["review"]
    assert review["differences"]
    assert any("caused" in d["detail_zh"] for d in review["differences"])
    assert "causality" in review["issue_types"]
    assert "The manager said the card caused the increase."[:40] in review["follow_up_zh"]
    assert "library" not in review["explanation_zh"].lower()
    assert_quotes_locatable(unknown_payload()["article_text"], review["quotes"])


def test_focus_kind_hint_used_by_mock(client):
    resp = client.post(ANALYZE, json=library_payload(focus_kind="purpose"))
    assert resp.status_code == 200
    types = resp.json()["review"]["issue_types"]
    assert "purpose" in types and "scope" in types


def test_guess_basis_no_definitive_cause(client):
    resp = client.post(ANALYZE, json=library_payload(answer_basis="guess"))
    assert resp.status_code == 200
    review = resp.json()["review"]
    assert review["definitive_cause"] is False
    assert "先不推断错因" in review["follow_up_zh"]


def test_dont_remember_basis_no_definitive_cause(client):
    resp = client.post(ANALYZE, json=library_payload(answer_basis="dont_remember"))
    assert resp.status_code == 200
    assert resp.json()["review"]["definitive_cause"] is False


def test_insufficient_material_needs_review(client):
    resp = client.post(ANALYZE, json=library_payload(evidence=[]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "needs_review"
    assert body["review"]["needs_review_reasons"][0]["code"] == "INSUFFICIENT_MATERIAL"


def test_invalid_option_id_rejected(client):
    resp = client.post(ANALYZE, json=library_payload(student_choice="E"))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_evidence_offset_mismatch_rejected(client):
    ev = evidence_of(LIBRARY_ARTICLE, LIBRARY_SENTENCES[1])
    ev["start"] += 1  # 偏移与引文不再逐字匹配
    resp = client.post(ANALYZE, json=library_payload(evidence=[ev]))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"


def test_mock_quote_keeps_selected_occurrence_with_unicode_prefix(client):
    quote = "Some students stayed."
    article = f"📚 {quote} {quote}"
    start = article.rindex(quote)
    evidence = {"quote": quote, "start": start, "end": start + len(quote)}

    resp = client.post(ANALYZE, json=library_payload(article_text=article, evidence=[evidence]))

    assert resp.status_code == 200
    returned = resp.json()["review"]["quotes"][0]
    assert (returned["text"], returned["start"], returned["end"]) == (quote, start, evidence["end"])


def test_evidence_not_in_article_rejected_without_echoing_content(client):
    resp = client.post(ANALYZE, json=library_payload(
        evidence=[{"quote": "A sentence that is not in the article."}]))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"
    assert LIBRARY_ARTICLE not in resp.text


def test_pydantic_error_does_not_echo_article(client):
    resp = client.post(ANALYZE, json=library_payload(student_choice="BB"))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert LIBRARY_ARTICLE not in resp.text


def test_rate_limit():
    app = create_app(make_settings(rate_limit_per_minute=2))
    with TestClient(app) as c:
        assert c.post(ANALYZE, json=library_payload()).status_code == 200
        assert c.post(ANALYZE, json=library_payload()).status_code == 200
        resp = c.post(ANALYZE, json=library_payload())
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "RATE_LIMITED"
        assert c.get("/healthz").status_code == 200  # 健康检查不受限流影响


def test_body_too_large():
    app = create_app(make_settings(max_body_bytes=1024))
    with TestClient(app) as c:
        resp = c.post(
            ANALYZE, json=library_payload(article_text="x" * 2000),
            headers={"Origin": "http://127.0.0.1:5500"},
        )
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "BODY_TOO_LARGE"
        assert resp.headers["Access-Control-Allow-Origin"] == "*"
