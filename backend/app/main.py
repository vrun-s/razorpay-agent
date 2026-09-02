import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.config import settings
from app.db import create_db_and_tables, engine
from app.gateway import get_gateway
from app.lifecycle import run_sweep
from app.routers import cases, observability, webhooks

logger = logging.getLogger(__name__)


async def _sweep_loop() -> None:
    """ADR-0008's in-process asyncio scheduler for the scheduled-sweep trigger (ADR-0005)."""
    gateway = get_gateway()
    while True:
        await asyncio.sleep(settings.sweep_interval_seconds)
        try:
            with Session(engine) as session:
                await asyncio.to_thread(run_sweep, session, gateway)
        except Exception:
            logger.exception("scheduled sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    # ADR-0015: the hosted demo is a static replay and sets SWEEP_ENABLED=false.
    sweep_task = asyncio.create_task(_sweep_loop()) if settings.sweep_enabled else None
    try:
        yield
    finally:
        if sweep_task is not None:
            sweep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweep_task


app = FastAPI(title="Recovery Engine", lifespan=lifespan)

# ADR-0015: only needed for the two-origin local dev setup. The one-port
# container serves UI and API from the same origin and sets DEV_CORS=false.
if settings.dev_cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(webhooks.router)
app.include_router(cases.router)
app.include_router(observability.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def config() -> dict[str, bool]:
    """Runtime flags the SPA needs at load time (ADR-0015). Currently just
    whether this instance rejects the human-action write endpoints."""
    return {"demo_readonly": settings.demo_readonly}


# ADR-0015 one-port collapse: when the built SPA is present, serve it from
# this same process so a single port answers both UI and API. Mounted last
# so every API route above wins; `html=True` serves index.html at "/".
# Guarded so a backend-only checkout (and the test suite) is unaffected.
if settings.static_dir.is_dir():
    app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="spa")
