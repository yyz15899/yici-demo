"""业务异常定义。

ApiError 由 main.py 的异常处理器转成统一错误响应体；
三个 Model* 异常由模型客户端抛出、analysis.py 捕获并映射为 503 错误码。
"""


class ApiError(Exception):
    """带 HTTP 状态码与前端可识别错误码的业务错误。

    http_status: 返回给前端的 HTTP 状态（422/429/503 等）
    code:        错误码，如 VALIDATION_ERROR / MODEL_TIMEOUT
    message_zh:  中文操作提示，前端可直接展示
    """

    def __init__(self, http_status: int, code: str, message_zh: str):
        self.http_status = http_status
        self.code = code
        self.message_zh = message_zh
        super().__init__(code)


class ModelNotConfiguredError(Exception):
    """服务端缺少模型配置（backend=openai 但地址/密钥/模型名不全）。"""


class ModelTimeoutError(Exception):
    """模型调用超过 MODEL_TIMEOUT_SECONDS。"""


class ModelInvalidOutputError(Exception):
    """模型输出无法解析或不符合 ModelAnalysis 固定结构（含上游 HTTP 错误）。"""