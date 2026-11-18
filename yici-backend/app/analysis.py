"""分析编排：校验 → 调模型 → 复核输出 → 组装 ok / needs_review 结果。

模型反馈一律是“建议”；引文编造、参考答案冲突、材料不足都转“待核对”，
模型未配置/超时/无效输出转 503 错误码。任何分支都不影响前端手动复盘。
"""

import logging

from .errors import (
    ApiError,
    ModelInvalidOutputError,
    ModelNotConfiguredError,
    ModelTimeoutError,
)
from .model.base import BaseModelClient
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    LocatedQuote,
    ReviewReason,
    ReviewResult,
)
from .validation import locate_quote, validate_request

logger = logging.getLogger("yici")

MODEL_ERROR_MESSAGES = {
    "MODEL_NOT_CONFIGURED": "自动分析未开启（服务端未配置模型）。可继续手动复盘，已填写的内容不受影响。",
    "MODEL_TIMEOUT": "自动分析超时。可稍后重试，或直接继续手动复盘，已填写的内容不受影响。",
    "MODEL_INVALID_OUTPUT": "自动分析返回了无效结果，已丢弃。可继续手动复盘，已填写的内容不受影响。",
}


async def run_analysis(req: AnalyzeRequest, client: BaseModelClient) -> AnalyzeResponse:
    """执行一次完整分析，返回统一响应体。

    步骤：
    1. validate_request：编号/证据前置校验（失败抛 ApiError 422）
    2. 材料不足（answer_basis=evidence 但没圈证据）→ 直接 needs_review，不调模型
    3. 调模型；三类模型异常映射为 503 + 错误码 + 中文提示
    4. 后置复核：模型每处引文必须在本次原文逐字定位，编造的剔除并记原因
    5. 参考答案冲突检查：模型 supported_option 与 reference_answer 不一致 → 待核对
    6. 猜的/记不清 → 强制 definitive_cause=False，不推断确定错因
    """
    located = validate_request(req)

    if req.answer_basis == "evidence" and not located:
        return AnalyzeResponse(
            status="needs_review",
            review=ReviewResult(
                status="needs_review",
                differences=[],
                quotes=[],
                explanation_zh="未提交圈选依据，暂无法给出自动分析。",
                follow_up_zh="请先在原文中圈出你认为支持自己选择的句子，再提交依据。",
                issue_types=[],
                definitive_cause=False,
                needs_review_reasons=[ReviewReason(
                    code="INSUFFICIENT_MATERIAL",
                    message_zh="缺少圈选依据，材料不足。请补充证据后重试，或直接手动复盘。",
                )],
            ),
        )

    try:
        out = await client.analyze(req, located)
    except ModelNotConfiguredError:
        raise ApiError(503, "MODEL_NOT_CONFIGURED", MODEL_ERROR_MESSAGES["MODEL_NOT_CONFIGURED"])
    except ModelTimeoutError:
        raise ApiError(503, "MODEL_TIMEOUT", MODEL_ERROR_MESSAGES["MODEL_TIMEOUT"])
    except ModelInvalidOutputError:
        raise ApiError(503, "MODEL_INVALID_OUTPUT", MODEL_ERROR_MESSAGES["MODEL_INVALID_OUTPUT"])

    reasons: list[ReviewReason] = []
    quotes: list[LocatedQuote] = []
    unlocatable = 0
    # 后置复核：模型引文必须逐字存在于本次提交的原文，否则视为编造并剔除
    for q in out.quotes:
        pos = locate_quote(req.article_text, q.text, q.start, q.end)
        if pos is None:
            unlocatable += 1
            continue
        start, end = pos
        quotes.append(LocatedQuote(
            text=q.text, start=start, end=end, option_id=q.option_id, note_zh=q.note_zh
        ))
    if unlocatable:
        reasons.append(ReviewReason(
            code="QUOTE_NOT_LOCATABLE",
            message_zh=f"有 {unlocatable} 处引文无法在本次原文中逐字定位，已剔除。请自行核对其余建议。",
        ))

    # 参考答案冲突：模型判断与参考答案不一致时不采信任何一方，转人工核对
    if (
        req.reference_answer
        and out.supported_option
        and out.supported_option.upper() != req.reference_answer.upper()
    ):
        reasons.append(ReviewReason(
            code="REFERENCE_CONFLICT",
            message_zh="自动分析与参考答案冲突，请优先人工核对，并可标记为待核对。",
        ))

    definitive = out.definitive and req.answer_basis not in ("guess", "dont_remember")
    status = "needs_review" if reasons else "ok"
    return AnalyzeResponse(
        status=status,
        review=ReviewResult(
            status=status,
            differences=out.differences,
            quotes=quotes,
            explanation_zh=out.explanation_zh,
            follow_up_zh=out.follow_up_zh,
            issue_types=out.issue_types,
            definitive_cause=definitive,
            needs_review_reasons=reasons,
        ),
    )
