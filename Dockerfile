# ADR-0015: single-container build of the Revenue Recovery demo — Node builds
# the SPA, the Python image serves it alongside the API on one port. This is
# the deploy unit for Render (bare *.onrender.com). Defaults: fake gateway,
# no keys, read-only, sweep off, ephemeral SQLite re-seeded on every boot.
#
#   docker build -t recovery-demo .
#   docker run --rm -p 8000:8000 recovery-demo   # -> http://localhost:8000

# ---- stage 1: build the frontend -------------------------------------------
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- stage 2: python runtime that serves API + built SPA ------------------
FROM python:3.13-slim AS runtime

RUN pip install --no-cache-dir uv

WORKDIR /app/backend
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY backend/ ./
RUN uv sync --frozen --no-dev
# Run the app straight from the resolved venv — no `uv` at container start.
ENV PATH="/app/backend/.venv/bin:$PATH"

# The built SPA; STATIC_DIR points main.py at it.
COPY --from=frontend /app/frontend/dist /app/static

# Hosted-demo defaults (ADR-0015). Override any of these in the Render
# dashboard; DATABASE_URL is left at its ./recovery.db default = ephemeral,
# re-seeded by the CMD on every boot.
ENV GATEWAY_BACKEND=fake \
    STATIC_DIR=/app/static \
    DEV_CORS=false \
    SWEEP_ENABLED=false \
    DEMO_READONLY=true \
    PORT=8000

EXPOSE 8000

# Render (and most PaaS) inject $PORT. Seed, then serve.
CMD ["sh", "-c", "python -m app.demo_seed && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
