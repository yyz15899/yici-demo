import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_settings(**overrides) -> Settings:
    base = dict(
        model_backend="mock",
        openai_base_url="",
        openai_api_key="",
        model_name="",
        model_timeout_seconds=30.0,
        max_body_bytes=65536,
        rate_limit_per_minute=1000,
        cors_origins="*",
        trust_proxy=False,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings():
    return make_settings()


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)