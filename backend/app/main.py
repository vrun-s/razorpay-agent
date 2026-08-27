import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    sweep_task = asyncio.create_task(_sweep_loop())
    try:
        yield
    finally:
        sweep_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweep_task


app = FastAPI(title="Recovery Engine", lifespan=lifespan)

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
