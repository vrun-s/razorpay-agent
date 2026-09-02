from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REPO_ROOT_ENV_FILE = _REPO_ROOT / ".env"


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

    # ADR-0015 (one-port collapse / hosted demo). Defaults preserve the
    # local two-terminal dev setup and the test suite unchanged; the
    # container image and Render override them.
    #
    # static_dir: when this directory exists, main.py serves it as the SPA
    # at "/" so a single process answers both UI and API. Default points at
    # the local `npm run build` output; unset/absent in a backend-only run,
    # so pytest is unaffected.
    static_dir: Path = _REPO_ROOT / "frontend" / "dist"
    # dev_cors: add the localhost:5173 CORS middleware (needed only for the
    # two-origin dev setup). The one-origin container sets this false.
    dev_cors: bool = True
    # sweep_enabled: run ADR-0005's in-process reassessment sweep. The
    # hosted demo is a static replay and a free-tier instance can't run a
    # timer reliably anyway, so it sets this false.
    sweep_enabled: bool = True
    # demo_readonly: reject the human-action write endpoints with 403 and
    # tell the frontend (via /config) to hide their controls. For the public
    # hosted instance only.
    demo_readonly: bool = False


settings = Settings()
