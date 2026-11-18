"""接口输入输出的 Pydantic 模型定义。

约定：
- 所有面向学生的文案字段以 _zh 结尾，内容为中文；引文保持英文原文。
- 长度上限在此集中定义（文章 20000 字符、选项 500、引文 1000 等），
  超限由 FastAPI 自动返回 422 VALIDATION_ERROR。
"""

from typing import Literal

from pydantic import BaseModel, Field

# 作答依据：有依据 / 排除法 / 猜的 / 记不清（后两者不推断确定错因）
AnswerBasis = Literal["evidence", "elimination", "guess", "dont_remember"]
# 三类可分析问题：范围扩大 / 例子目的 / 相关与因果
IssueType = Literal["scope", "purpose", "causality"]
# 错项差异类型：多说了 / 漏说了 / 答偏了
DiffKind = Literal["added", "omitted", "shifted"]


class OptionIn(BaseModel):
    """一个选项：编号 + 文本。"""

    id: str = Field(pattern=r"^[A-Za-z]$", description="选项编号，单个字母")
    text: str = Field(min_length=1, max_length=500)


class EvidenceIn(BaseModel):
    """学生圈出的一处原文证据。

    start/end 为原文字符偏移，可省略；提供时服务端会逐字校验
    article_text[start:end] == quote，不一致返回 422 EVIDENCE_NOT_FOUND。
    """

    quote: str = Field(min_length=1, max_length=1000, description="逐字引文")
    start: int | None = Field(default=None, ge=0, description="在原文中的起始字符偏移")
    end: int | None = Field(default=None, ge=0, description="结束偏移（不含）")


class AnalyzeRequest(BaseModel):
    """POST /api/v1/reviews/analyze 的请求体。

    只包含本次复盘所需材料；不要携带个人笔记全文或剧情存档。
    reference_answer / reference_explanation 可省略，缺参考答案仍可分析。
    """

    article_text: str = Field(min_length=1, max_length=20000)
    question_stem: str = Field(min_length=1, max_length=1000)
    options: list[OptionIn] = Field(min_length=2, max_length=8)
    student_choice: str = Field(pattern=r"^[A-Za-z]$")
    compare_choice: str = Field(pattern=r"^[A-Za-z]$")
    answer_basis: AnswerBasis = "evidence"
    evidence: list[EvidenceIn] = Field(default_factory=list, max_length=10)
    reference_answer: str | None = Field(default=None, pattern=r"^[A-Za-z]$")
    reference_explanation: str | None = Field(default=None, max_length=2000)
    focus_kind: IssueType | None = Field(
        default=None, description="学生自选的核对类别，仅作为模型提示，不参与校验"
    )


class LocatedEvidence(BaseModel):
    """服务端校验通过后、确定可在原文逐字定位的证据。"""

    quote: str
    start: int
    end: int


class DiffItem(BaseModel):
    """两个选项之间的一条具体差异（多说/漏说/答偏）。"""

    kind: DiffKind
    detail_zh: str = Field(min_length=1, max_length=500)


class QuoteOut(BaseModel):
    """模型返回的一处引文（尚未复核，可能无法定位）。"""

    text: str = Field(min_length=1, max_length=1000)
    option_id: str | None = None
    note_zh: str = Field(default="", max_length=300)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)


class ModelAnalysis(BaseModel):
    """模型必须返回的固定结构，服务端逐项校验。

    不符合此结构（JSON 解析失败/字段缺失/超长）→ 503 MODEL_INVALID_OUTPUT。
    supported_option 为模型认为原文支持的选项，用于与参考答案做冲突检查；
    mock 客户端恒为 None（不判正确答案）。
    """

    differences: list[DiffItem] = Field(min_length=1, max_length=6)
    quotes: list[QuoteOut] = Field(default_factory=list, max_length=6)
    explanation_zh: str = Field(min_length=1, max_length=2000)
    follow_up_zh: str = Field(min_length=1, max_length=500)
    issue_types: list[IssueType] = Field(default_factory=list, max_length=3)
    supported_option: str | None = None
    definitive: bool = True


class LocatedQuote(BaseModel):
    """已复核、可在本次原文中逐字定位的引文，前端可直接用 start/end 高亮回跳。"""

    text: str
    start: int
    end: int
    option_id: str | None = None
    note_zh: str = ""


class ReviewReason(BaseModel):
    """一条“待核对”原因：code 供前端识别，message_zh 可直接展示。"""

    code: str
    message_zh: str


class ReviewResult(BaseModel):
    """分析结果主体。

    advisory 恒为 "suggestion"：所有模型反馈都是建议，由学生纠正或自评，
    不参与独立复测判定。definitive_cause=False 时前端不得展示确定错因
    （猜的/记不清路径，或模型自认不确定）。
    """

    status: Literal["ok", "needs_review"]
    advisory: Literal["suggestion"] = "suggestion"
    differences: list[DiffItem]
    quotes: list[LocatedQuote]
    explanation_zh: str
    follow_up_zh: str
    issue_types: list[IssueType]
    definitive_cause: bool
    needs_review_reasons: list[ReviewReason] = Field(default_factory=list)


class ErrorBody(BaseModel):
    """错误信息：code 供前端分支处理，message_zh 为中文操作提示。"""

    code: str
    message_zh: str


class AnalyzeResponse(BaseModel):
    """analyze 接口统一响应体。

    status=ok/needs_review 时 HTTP 200，review 有值；
    status=error 时 HTTP 4xx/5xx，error 有值。
    任何非 ok 结果前端都应保留用户已填内容，允许继续手动复盘。
    """

    status: Literal["ok", "needs_review", "error"]
    review: ReviewResult | None = None
    error: ErrorBody | None = None


class HealthResponse(BaseModel):
    """GET /healthz 响应：进程存活即 ok，model_configured 反映自动分析可用性。"""

    status: Literal["ok"]
    version: str
    model_backend: str
    model_configured: bool
