  # Handoff — Portability / containerisation / hosting discussion

**Date:** 2026-09-01
**Project:** Razorpay Revenue Recovery (Track 3, Buildathon 2026, solo build)
**Branch:** `master` (clean — no code written this session)
**Next session:** continue *discussing* portability/hosting/local-LLM verification. Nothing has been implemented yet; this was an advisory conversation only.

---

## What this session was

Pure discussion. The user asked how to make the app more portable, whether to containerise, whether Fly.io fits, whether an Anthropic key is unavoidable, and whether a local LLM can stand in for verification. No files changed. The output was a recommended plan (below) plus analysis of the LLM seam.

## Project facts established (verified against the repo this session)

- **Backend:** FastAPI + SQLModel over SQLite, managed by `uv`, Python 3.13. `backend/.python-version` exists → `uv` auto-fetches the interpreter, so "install Python 3.13" is effectively not a prereq.
- **Frontend:** React 19 + Vite + Tailwind v4, static SPA, polls backend every 3s. `frontend/src/api.ts:1` — `const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'`.
- **CORS:** hardcoded in `backend/app/main.py:46-48` to `http://localhost:5173` / `127.0.0.1:5173`.
- **Runs fully offline:** default `GATEWAY_BACKEND=fake` + `FakeLLMClient` fallback when `ANTHROPIC_API_KEY` unset. 251 backend tests pass with no credentials.
- **Scheduled sweep:** `SWEEP_INTERVAL_SECONDS=300` — in-process background loop; drives reassessments, which call the LLM. Relevant to any always-on hosting decision.
- **Real-Razorpay path:** currently needs a public webhook URL via `ssh -R 80:localhost:8000 nokey@localhost.run`, re-registered in the Razorpay dashboard every session because the URL changes (README, "Running against real Razorpay test mode").
- **Lockfiles present:** `backend/uv.lock`, `frontend/package-lock.json`. No `Makefile`/`justfile`/`Dockerfile`/compose anywhere yet.
- Deeper context: `README.md`, `CONTEXT.md`, `docs/adr/` (14 ADRs). ADR-0006 = estimator is Beta-Bernoulli, never an LLM guess. ADR-0007 = evaluation integrity / real-execution slice is a small ~20-25 case proof. ADR-0008 = Anthropic-backed LLM client. ADR-0014 = flat incentive model.

## The LLM seam (`backend/app/llm.py`) — verified in full this session

- Only file touching the `anthropic` SDK. Grep for `tools=`/`tool_choice`/`tool_use`/`response_format`/`.beta`/`json_schema` across `backend/app/` → **nothing**. No tool calling, no structured output, no agentic loop anywhere in the project.
- `LLMClient` is a 3-method `Protocol`: `diagnose_failure_reason`, `generate_justification`, `flag_escalation`. Implementations: `AnthropicLLMClient`, `FakeLLMClient`. Selected by `get_llm_client()` on `settings.anthropic_api_key` presence. Same fake/real seam idiom as `gateway.py` (`GATEWAY_BACKEND`).
- `AnthropicLLMClient`: `Anthropic(api_key=...)` with **no `base_url`**; model **hardcoded** `_MODEL = "claude-haiku-4-5-20251001"`; single `messages.create(model, max_tokens, messages=[{role:user, content:prompt}])`, returns `response.content[0].text.strip()`. No system prompt.
- Output parsing is forgiving: `diagnose` lowercases + exact-membership-checks an 8-tuple, else `"unknown"`; `generate_justification` is free text (no parse); `flag_escalation` is `.lower().startswith("y")`.
- `config.py` only has `anthropic_api_key: str | None = None` — no base_url / model override fields.

---

## The recommended plan (as delivered — not yet accepted or started)

### Phase 1 — One-port collapse + task runner (do regardless, ~half day)
- Add `server.proxy` to `vite.config.ts` so `vite dev` proxies an `/api` prefix to `:8000` (keeps HMR).
- Frontend API base → `?? ''` (relative) so the bundled build hits its own origin.
- FastAPI mounts `StaticFiles(directory=<frontend/dist>, html=True)` at `/`, guarded by a dir-exists check so backend-only test runs still work.
- Gate the CORS middleware behind a dev-only flag.
- Add `justfile`/`Makefile`/`run.sh`: `setup`, `seed`, `dev`, `demo`, `test`.
- Done-check: fresh clone → one command → single process on `:8000` serves UI + API, seeded, no Node running.

### Phase 2 — Webhook stability (only when starting the real-Razorpay slice, ~30 min)
- Named Cloudflare Tunnel or ngrok reserved domain → one stable hostname, registered in Razorpay **once**.
- Replace the README "re-register every session" note.
- Treated as a **separate now-decision**, not folded into the hosting decision.

### Phase 3 — Container (after Phase 1, ~1-2 hrs)
- Multi-stage Dockerfile: node build stage → Python runtime, copy `dist/` in. `CMD` = run `app.demo_seed` then `uvicorn`. `.dockerignore`.
- Defaults `GATEWAY_BACKEND=fake`, no keys. SQLite **ephemeral** (seed on start) — correct for a demo.
- Keep the `uv`/`npm` quickstart as the README's primary path; Docker is the "install nothing" fallback.
- Explicitly **not**: compose, nginx sidecar, Postgres, k8s, containerising the Vite dev server.

### Phase 4 — Hosting decision (decide early, don't discover late)
- Decision is the user's: is a live URL actually required for submission, or is it video + repo? Default = **video-only, no deploy** unless there's a concrete requirement. Make the call before the final third of remaining time.
- If a live link is required, **spike Fly.io early** (while there's slack to fall back):
  - `fly.toml` with `min_machines_running = 1` (else the sweep suspends between requests), **512MB** (256 likely OOMs on the `anthropic` SDK import), a volume mounted with `DATABASE_URL` pointed at it, `fly secrets set`.
  - Verify the sweep actually fires over 10+ min of logs and survives a redeploy.
  - If the spike runs past ~half a day, abandon it → video-only. Phase 3 still stands alone.
- The Fly step is **not configless** — the Dockerfile is unchanged, the deployment has a real checklist (above).

## Position on the sub-questions

- **Anthropic key with credits:** not needed to *build* anything, incl. all four phases (FakeLLMClient is a real fallback; eval numbers come from the simulator + counterfactual replay, not the LLM). Needed **late and briefly**: (1) recording the pitch video — canned deterministic narration reads badly for an "AI agent" demo; (2) one real Haiku run to confirm prompts don't error / parse / read well. Cost is cents-to-low-dollars (Haiku, 3 bounded calls per reassessment). Check whether the buildathon hands out credits.
- **Hosted instance with a real key:** the sweep drives LLM calls continuously while any case is open (ongoing spend, not one-time); it's a public URL so anyone hitting it spends the key. Deploy with the fake LLM (zero spend, still a full demo); run real Claude only locally for the video.
- **Local LLM for verification (Option A):** add a third `LocalLLMClient(LLMClient)` calling Ollama's native API via `httpx` (already a dep), switched on a `settings.llm_backend` value `"fake"|"anthropic"|"local"` mirroring `GATEWAY_BACKEND`. ~40 lines, no new deps, fits the repo idiom. (Option B = add `base_url`/model override + run a LiteLLM proxy speaking Anthropic `/v1/messages` — more moving parts, trusts the proxy shim.)
  - **No tool calling to worry about** — confirmed by grep. The three roles are plain text completion.
  - Llama 3.1 8B / Qwen 2.5 handle all three (8-way classify, one-sentence gen, yes/no). Only soft spot: `diagnose_failure_reason` — 8B tends to preamble ("The category is: ..."), which fails the exact-string match and silently becomes `"unknown"`, skewing that estimator cell. Fix with few-shot or a substring match if it matters in the harness.
  - A local LLM verifies **plumbing + prompt sanity**, not the real SDK network path (only Option B does) and not video-quality tone. Doesn't remove the "one real Haiku run before submission" step — just makes it a formality.

---

## Suggested skills for the next agent

- **`domain-modeling`** — if the discussion lands on a decision worth recording, this repo keeps ADRs under `docs/adr/` and a `CONTEXT.md`. A "how we ship/run/deploy the demo" choice (one-port collapse, container-as-fallback, local-LLM verification client, hosting stance) is ADR-shaped. Use it to write/edit the ADR or CONTEXT entry.
- **`grilling`** — if the user wants the plan stress-tested rather than extended, this pushes back hard on the reasoning (they explicitly asked for criticism this session and responded well to it).
- **`wizard`** — only if the session turns to *doing* the Fly spike or tunnel setup: a bash wizard for the human-only steps (Fly account, `fly launch`, `fly secrets set`, registering the webhook URL in the Razorpay dashboard).
- **`update-config`** — if a `justfile`/task-runner or new `.env`/settings keys (`llm_backend`, `anthropic_base_url`) actually get added and need permissions/hooks wired.

Do **not** spawn subagents unless the user asks. This has been a single-thread advisory conversation; keep it that way.

## Memory to consider writing (if the next session confirms a direction)

- A `project` memory: portability plan = 4 phases, one-port collapse first, container as fallback, Fly only on an explicit live-link requirement, local-LLM `LlmClient` for offline verification. Currently **advisory only, nothing accepted**.
