"""服务端配置：全部从环境变量（或项目根 .env）读取。

密钥只存在于服务端进程内，不会出现在任何响应或日志中。
Settings 为不可变数据类，测试可显式传参构造，不依赖真实环境变量。
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    """读取整型环境变量，非法值回退默认（避免启动即崩）。"""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """运行配置。各字段含义与默认值见 .env.example / README。"""

    # mock=确定性模拟模型（联调）；openai=OpenAI 兼容真实模型
    model_backend: str = field(default_factory=lambda: os.getenv("MODEL_BACKEND", "mock").lower())
    openai_base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "").rstrip("/"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    model_name: str = field(default_factory=lambda: os.getenv("MODEL_NAME", ""))
    model_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("MODEL_TIMEOUT_SECONDS", "30")))
    max_body_bytes: int = field(default_factory=lambda: _int("MAX_BODY_BYTES", 65536))
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 10))
    cors_origins: str = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "*"))
    trust_proxy: bool = field(default_factory=lambda: os.getenv("TRUST_PROXY", "false").lower() == "true")

    @property
    def model_configured(self) -> bool:
        """自动分析是否可用。healthz 据此告知前端，未配置不影响健康检查本身。"""
        if self.model_backend == "mock":
            return True
        if self.model_backend == "openai":
            return bool(self.openai_base_url and self.openai_api_key and self.model_name)
        return False