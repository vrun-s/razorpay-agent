from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ROOT_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./recovery.db"

    # ADR-0005: how long an OPEN case waits for an outcome before the
    # scheduled sweep treats silence as a reassessment trigger, and how
    # often that sweep runs.
    response_window_seconds: int = 3600
    sweep_interval_seconds: int = 300

    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    razorpay_webhook_url: str | None = None

    # ticket 13: which Gateway implementation get_gateway() hands out. "fake"
    # (default) keeps every existing ticket's behavior unchanged; "razorpay"
    # makes real calls against Razorpay test mode using the credentials above.
    gateway_backend: Literal["fake", "razorpay"] = "fake"

    anthropic_api_key: str | None = None


settings = Settings()
