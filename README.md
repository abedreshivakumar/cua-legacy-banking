# cua — computer-use automation for legacy UIs

A system that lets an LLM learn a task once on a legacy, API-less web app, then run it again — deterministically, with no model call — forever after.

The model discovers. The run compiles into a typed, reviewable **capability**. Replay is how an AI agent invokes that capability in production.

See `docs/DECISIONS.md` for the design rationale and every non-obvious call made along the way, and `artifacts/adopted_standards.md` for the engineering conventions this project holds itself to.

## Status

This is a work in progress, built story by story. What's real today:

| Piece | Status |
|---|---|
| Mock legacy target app (frameset, nested tables, no test IDs, injectable faults) | ✅ built |
| Capability artifact schema (typed inputs/outputs, ranked element-targeting strategies, condition language) | ✅ built |
| Frame-aware hit-testing + the shared target resolver | ✅ built |
| Deterministic replay engine + the `succeeded \| business_outcome \| failed \| escalated \| blocked_pending_approval` result contract | ✅ built |
| `cua replay` CLI | ✅ built |
| LLM-driven discovery loop (`claude-opus-5-5`, computer-use toolset) | 🚧 in progress — a capped dev spike exists (`scripts/spike_g0.py`), the production `cua discover` command does not yet |
| Compiler (discovery trace → reviewable capability) | 🚧 not yet started |
| Human-in-the-loop handoff, safety/approval gate, redaction | 🚧 not yet started |

The demo path below reflects what's real right now: replaying a hand-written capability against the mock app. Once discovery and the compiler land, this README will show the full `discover → compile → replay` flow the brief asks for.

## Setup

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
make setup   # uv sync + playwright install chromium
cp .env.example .env
```

Fill in `.env`:

```
ANTHROPIC_API_KEY=       # only needed for discovery (scripts/spike_g0.py) — not needed for replay or tests
COREBANK_USER=teller1
COREBANK_PASSWORD=       # pick anything; the mock app just needs it to match on login
COREBANK_PORT=8800
```

## Running without live services

Everything except the discovery spike runs fully offline — no API key, no network:

```bash
make test   # starts the mock app in-process per test, no external services
```

32 tests pass as of this writing: the hostile mock app, every fault mode, the hit-test resolver, the artifact schema, the ranked-strategy resolver, and the replay engine against real seeded data.

## Demo path

**1. Start the mock legacy banking app:**

```bash
make app   # http://127.0.0.1:8800
```

**2. Replay the hand-written `member_inquiry` capability** (`capabilities/member_inquiry/0.0.1.yaml`) against it — no model call, fully deterministic:

```bash
# A member that exists
uv run cua replay capabilities/member_inquiry/0.0.1.yaml --input member_no=100007

# A member that doesn't — a legitimate business outcome, not a crash
uv run cua replay capabilities/member_inquiry/0.0.1.yaml --input member_no=999999
```

Each prints the typed `RunResult` as JSON and exits 0 for `succeeded`/`business_outcome`, nonzero otherwise:

```json
{
  "run_id": "...",
  "capability": "member_inquiry",
  "version": "0.0.1",
  "status": "succeeded",
  "outputs": { "savings_balance": "2345.67" },
  "trace": [
    { "step_id": "enter_member_no", "strategy_used": "attr", "duration_ms": 9 },
    { "step_id": "submit_search", "strategy_used": "text", "duration_ms": 54 }
  ]
}
```

Add `--headed` to watch the browser instead of running headless, and `--base-url` if the mock app isn't on the default port.

**3. (Costs a small amount of API credit) Run the G0 discovery spike** — a capped, 6-step live `claude-opus-5-5` run against the mock app, proving the computer-use toolset and the frame-aware hit-test work together:

```bash
uv run python scripts/spike_g0.py
```

This is a dev-only script, not the production discovery command — see `docs/DECISIONS.md`'s "G0 spike" entry.

## Repo layout

```
target_app/        the mock legacy banking UI (FastAPI + Jinja), with fault injection via POST /__faults
src/cua/
  artifact/         the capability schema, condition language, YAML/JSON store
  surface/          frame-aware hit-testing and the ranked-strategy element resolver
  replay/           the deterministic replay engine and result contract
  cli.py            `cua replay`, `cua version`
capabilities/       capability artifacts (currently: member_inquiry 0.0.1, hand-written)
tests/              unit + integration tests (integration tests run a real Playwright browser against the real mock app)
scripts/spike_g0.py the dev-only live discovery spike
docs/DECISIONS.md   the decision log — design choices, alternatives, and bugs found along the way
```

## Running the mock app's fault injection

```bash
curl -X POST http://127.0.0.1:8800/__faults \
  -d "kind=interstitial&mode=once&routes=/fr/work/inq/result"
```

`kind` is one of `interstitial | slow | http500 | permission_denied | session_expire | relabel`; `mode` is `once | always | nth:<k>`. See `target_app/faults.py`.
