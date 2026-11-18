"""一词之差 · 自动分析后端入口。

提供两个 HTTP JSON 接口：
- GET  /healthz                部署健康检查（模型未配置时仍可用）
- POST /api/v1/reviews/analyze  选项比较自动分析（先校验、后调模型、再复核引文）

服务无状态：不落盘任何用户内容，题目/笔记/进度由前端保存在浏览器 IndexedDB。
"""

import logging
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .analysis import run_analysis
from .config import Settings
from .errors import ApiError, ModelNotConfiguredError
from .model.base import BaseModelClient
from .model.mock import MockModelClient
from .model.openai_compat import OpenAICompatClient
from .ratelimit import SlidingWindowLimiter
from .schemas import AnalyzeRequest, AnalyzeResponse, HealthResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("yici")

VERSION = "1.0.0"


class _UnconfiguredClient(BaseModelClient):
    """MODEL_BACKEND 取值非法时的兜底客户端：一律按“模型未配置”处理。"""

    async def analyze(self, req, evidence):
        raise ModelNotConfiguredError()


def build_client(settings: Settings) -> BaseModelClient:
    """按环境变量选择模型客户端：mock（联调）/ openai（真实模型）/ 兜底。"""
    if settings.model_backend == "mock":
        return MockModelClient()
    if settings.model_backend == "openai":
        return OpenAICompatClient(settings)
    return _UnconfiguredClient()


def _error_response(http_status: int, code: str, message_zh: str) -> JSONResponse:
    """统一错误响应体：{status:"error", review:null, error:{code, message_zh}}。

    前端按 error.code 识别错误类型；message_zh 可直接展示给学生。
    """
    return JSONResponse(
        status_code=http_status,
        content={"status": "error", "review": None, "error": {"code": code, "message_zh": message_zh}},
    )


class BodyLimitMiddleware:
    """请求体大小限制（默认 64KB，MAX_BODY_BYTES 可配）。

    纯 ASGI 实现：先缓冲整个请求体并计数，超限直接回 413 BODY_TOO_LARGE；
    未超限则把缓冲后的 body 重放给下游。不用 BaseHTTPMiddleware 是因为
    它消费流后下游 FastAPI 会收不到 body（曾导致全部请求 422）。
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length and length.isdigit() and int(length) > self._max_bytes:
            await self._reject(send)
            return

        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > self._max_bytes:
                await self._reject(send)
                return
            if not message.get("more_body", False):
                break

        async def replay():
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)

    async def _reject(self, send):
        payload = _error_response(
            413, "BODY_TOO_LARGE", "提交内容过大，请精简文章或分批导入后重试。"
        )
        await send({"type": "http.response.start", "status": 413, "headers": payload.headers.raw})
        await send({"type": "http.response.body", "body": payload.body})


def create_app(settings: Settings | None = None) -> FastAPI:
    """应用工厂。测试可传入定制 Settings（如更小限流/请求体上限）独立建 app。"""
    settings = settings or Settings()
    app = FastAPI(title="一词之差 · 自动分析后端", version=VERSION)
    app.state.settings = settings
    app.state.model_client = build_client(settings)
    app.state.limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)

    # 让 CORS 包住请求体限制，以便跨域前端也能读取 413 响应。
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        """业务错误（校验失败、模型不可用等）→ 统一错误体 + 对应 HTTP 状态码。"""
        return _error_response(exc.http_status, exc.code, exc.message_zh)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        """Pydantic 校验失败 → 422 VALIDATION_ERROR。

        只回显字段路径与错误类型，不回显输入值，
        避免把导入原文/个人笔记带进响应与日志。
        """
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        max_length = first.get("ctx", {}).get("max_length")
        length_limits = {
            "article_text": ("英文原文", "个字符"),
            "question_stem": ("题干", "个字符"),
            "evidence": ("圈选依据", "条"),
            "options": ("选项", "项"),
        }
        limit = length_limits.get(loc)
        if loc.startswith("options.") and loc.endswith(".text"):
            limit = ("单个选项", "个字符")
        if loc.startswith("evidence.") and loc.endswith(".quote"):
            limit = ("单条圈选依据", "个字符")
        if max_length is not None and limit:
            label, unit = limit
            return _error_response(
                422, "VALIDATION_ERROR",
                f"{label}最多允许 {max_length} {unit}。请精简材料，或继续手动复盘。",
            )
        detail = f"输入校验失败：字段 {loc or '(root)'}（{first.get('type', 'unknown')}）。" \
                 "请检查选项编号格式、内容长度或字段是否缺失。"
        return _error_response(422, "VALIDATION_ERROR", detail)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        """未预期异常 → 500 INTERNAL_ERROR。日志只记异常类型，不记内容。"""
        logger.error("unhandled exception type=%s", type(exc).__name__)
        return _error_response(500, "INTERNAL_ERROR", "服务内部错误。可继续手动复盘，稍后再试自动分析。")

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz():
        """健康检查，供部署探活。

        永远返回 200（只要进程活着）；model_configured 字段告知前端
        自动分析是否可用，未配置时前端应隐藏入口或提示，但不影响手动复盘。
        """
        return HealthResponse(
            status="ok",
            version=VERSION,
            model_backend=settings.model_backend,
            model_configured=settings.model_configured,
        )

    @app.post("/api/v1/reviews/analyze", response_model=AnalyzeResponse)
    async def analyze(req: AnalyzeRequest, request: Request):
        """选项比较自动分析。

        流程：限流 → 服务端校验（编号/长度/证据逐字定位）→ 调模型 →
        引文复核与参考答案冲突检查 → ok / needs_review。
        模型未配置/超时/无效输出 → 503 + 错误码，前端可继续手动复盘。
        日志只记录结果状态与耗时，不记录原文、笔记或密钥。
        """
        started = time.monotonic()
        ip = request.client.host if request.client else "unknown"
        if settings.trust_proxy:
            # 仅在可信反向代理后才按 X-Forwarded-For 限流，防止客户端伪造绕过
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                ip = forwarded.split(",")[0].strip()
        if not request.app.state.limiter.allow(ip):
            return _error_response(429, "RATE_LIMITED", "请求过于频繁，请稍等一分钟再试。可先继续手动复盘。")

        code = "-"
        try:
            result = await run_analysis(req, request.app.state.model_client)
            code = result.status
            return result
        except ApiError as exc:
            code = exc.code
            raise
        finally:
            logger.info(
                "analyze status=%s duration_ms=%d", code, int((time.monotonic() - started) * 1000)
            )

    return app


app = create_app()
