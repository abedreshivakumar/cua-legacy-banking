# cua — computer-use automation for legacy UIs

A system that lets an LLM learn a task once on a legacy, API-less web app, then run it again — deterministically, with no model call — forever after.

The model **discovers**. The run **compiles** into a typed, reviewable **capability** artifact. **Replay** is how an AI agent invokes that capability in production, with no model in the loop. A human can take over mid-run when the system gets stuck, and a policy/approval gate stands between the agent and anything irreversible.

See [`REPORT.md`](REPORT.md) for the full design writeup, [`docs/DECISIONS.md`](docs/DECISIONS.md) for the decision log and every real bug found building this, and [`artifacts/adopted_standards.md`](artifacts/adopted_standards.md) for the engineering conventions this project holds itself to.


## Setup

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
make setup   # uv sync + playwright install chromium
cp .env.example .env
```

Fill in `.env`:

```
ANTHROPIC_API_KEY=       # only needed for a live discovery run (spike_g0.py, collect_evidence_live.py) — not for replay or tests
COREBANK_USER=teller1
COREBANK_PASSWORD=       # pick anything; the mock app just needs it to match on login
COREBANK_PORT=8800
```

## Running without live services

Everything except the G0 spike runs fully offline — no API key, no network, real browser + real mock app:

```bash
make test   # starts the mock app in-process per test
```

77 tests pass as of this writing, including the hostile mock app, every fault mode, discovery/compile/replay/recovery against a real browser, the policy and approval gate, redaction (text + pixel), and the live-session handoff — all with a `ScriptedModelClient` standing in for the API.

## Demo path

**1. Start the mock legacy banking app:**

```bash
make app   # http://127.0.0.1:8800
```

**2. Replay the hand-written `member_inquiry` capability** (`capabilities/member_inquiry/0.0.1.yaml`) — read-only, no model call, fully deterministic:

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
    { "step_id": "enter_member_no", "strategy_used": "attr", "duration_ms": 9, "drifted": false },
    { "step_id": "submit_search", "strategy_used": "text", "duration_ms": 54, "drifted": false }
  ]
}
```

Add `--headed` to watch the browser instead of running headless, and `--base-url` if the mock app isn't on the default port.

**3. The transfer flow and the safety gate.** `capabilities/transfer_funds/0.0.1.yaml` is `irreversible_write` — `cua replay` doesn't wire up the policy/approval gate by default (there's no commit route to protect without one configured), so this flow is exercised directly against `src/cua/replay/engine.py`'s `policy`/`approval_store` parameters in `tests/integration/test_policy_approval.py`, not the CLI. Run that file to see it live: no approval record → `blocked_pending_approval`; with one → succeeds and returns a real confirmation number, consuming the record; reusing it → a hard `policy_denied`.

**4. Live-session handoff.** When a discovery run calls `request_human`, it writes a control lease a separate operator process can see:

```bash
uv run cua control status --lease-path .cua/control_lease.json
uv run cua control release --lease-path .cua/control_lease.json
```

`tests/integration/test_control_handoff.py` shows the full loop: a human attaches over CDP to the agent's own live browser, confirms it's the real DOM state (not a snapshot), releases the lease, and discovery resumes rather than terminating.

**5. Evidence.** Runs the real discovery → compile → replay pipeline and writes a reviewable bundle:

```bash
make evidence        # offline — writes evidence/demo_member_inquiry/, a ScriptedModelClient demo run
uv run python scripts/collect_evidence_live.py   # costs real API credit — a genuine live claude-opus-5-5 run
```

The live one is already in the repo at `evidence/live_member_inquiry/` — a real discovery session, compiled into `member_inquiry_live-0.0.1.yaml`, then replayed deterministically. It's also what caught a real bug the offline fixtures couldn't: every scripted test hardcodes the declared input's name as `member_no`, but a real model is free to name it anything — this run named it `member_number` — and the first version of this script assumed the fixture convention and crashed on replay until it was fixed to read the name back off the compiled capability (`docs/DECISIONS.md` D30).

**6. (Costs a small amount of real API credit) The G0 discovery spike** — a capped, 6-step live `claude-opus-5-5` run proving the computer-use toolset and the frame-aware hit-test work together:

```bash
make discover-spike
```

This is a dev-only script, not the production discovery path — see `docs/DECISIONS.md`'s "G0 spike" entry.

## Repo layout

```
target_app/           the mock legacy banking UI (FastAPI + Jinja): frameset, nested tables, no test IDs,
                       fault injection via POST /__faults, a real (gated) transfer flow
src/cua/
  artifact/            the capability schema, condition language, element-targeting strategies, YAML/JSON store
  surface/             frame-aware hit-testing and the ranked-strategy element resolver
  discovery/           the LLM-driven discovery loop, custom tools, probe-run detector synthesis
  compile/             discovery trace -> reviewable draft Capability
  replay/               the deterministic replay engine, recovery handlers, result contract
  safety/              the network policy guard, commit-approval store, text + pixel redaction
  control/             the control lease and the terminal operator's CDP attach
  evidence/            transcript/replay-log writers and INDEX.md generation
  cli.py               `cua replay`, `cua control status/release`, `cua version`
capabilities/          capability artifacts: member_inquiry (read-only), transfer_funds (irreversible_write)
evidence/              evidence bundles: demo_member_inquiry/ (offline), live_member_inquiry/ (real live run)
tests/                 unit + integration tests (integration tests run a real Playwright browser against the real mock app)
scripts/
  spike_g0.py                the dev-only capped live discovery spike
  collect_evidence.py        the offline evidence script (make evidence)
  collect_evidence_live.py   the real evidence script — live API calls
docs/DECISIONS.md      the decision log — design choices, alternatives, and every real bug found along the way
```

## Running the mock app's fault injection

```bash
curl -X POST http://127.0.0.1:8800/__faults \
  -d "kind=interstitial&mode=once&routes=/fr/work/inq/result"
```

`kind` is one of `interstitial | slow | http500 | permission_denied | session_expire | relabel`; `mode` is `once | always | nth:<k>`. See `target_app/faults.py`.
