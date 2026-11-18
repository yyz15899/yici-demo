"""模型调用前的服务端输入校验。

原则：先校验、后调模型。编号/长度/证据定位不合法时直接拒绝，
不浪费模型调用，也不把非法材料送给模型。
"""

from .errors import ApiError
from .schemas import AnalyzeRequest, LocatedEvidence


def validate_request(req: AnalyzeRequest) -> list[LocatedEvidence]:
    """校验选项编号与证据逐字定位，返回已定位的证据列表。

    长度/格式约束已由 Pydantic 完成，这里做跨字段语义校验：
    - 选项编号不重复；student/compare/reference 编号必须存在于选项中
    - student 与 compare 不能相同
    - 每条证据必须能在本次原文中逐字定位

    Raises:
        ApiError(422, VALIDATION_ERROR): 编号类问题
        ApiError(422, EVIDENCE_NOT_FOUND): 证据无法逐字定位
    """
    ids = [o.id.upper() for o in req.options]
    if len(set(ids)) != len(ids):
        raise ApiError(422, "VALIDATION_ERROR", "选项编号重复，请检查导入的选项。")

    student = req.student_choice.upper()
    compare = req.compare_choice.upper()
    if student not in ids or compare not in ids:
        raise ApiError(422, "VALIDATION_ERROR", "所选编号不在本题选项中，请重新选择要比较的两个选项。")
    if student == compare:
        raise ApiError(422, "VALIDATION_ERROR", "要比较的两个选项不能相同。")
    if req.reference_answer and req.reference_answer.upper() not in ids:
        raise ApiError(422, "VALIDATION_ERROR", "参考答案编号不在本题选项中，请核对后重试。")

    located: list[LocatedEvidence] = []
    for i, ev in enumerate(req.evidence, start=1):
        pos = locate_quote(req.article_text, ev.quote, ev.start, ev.end)
        if pos is None:
            raise ApiError(
                422,
                "EVIDENCE_NOT_FOUND",
                f"第 {i} 条证据无法在原文中逐字定位，请回到原文重新圈选后再提交。",
            )
        start, end = pos
        located.append(LocatedEvidence(quote=ev.quote, start=start, end=end))
    return located


def locate_quote(
    article_text: str, quote: str, start: int | None = None, end: int | None = None
) -> tuple[int, int] | None:
    """逐字定位引文，返回 (start, end)；无法定位返回 None。

    给了偏移：必须 article_text[start:end] == quote 精确一致（不做任何归一化）。
    未给偏移：在原文中查找首次出现。
    同时用于两处：提交证据的前置校验、模型输出引文的后置复核。
    """
    if start is not None and end is not None:
        if 0 <= start < end <= len(article_text) and article_text[start:end] == quote:
            return start, end
        return None
    idx = article_text.find(quote)
    if idx == -1:
        return None
    return idx, idx + len(quote)