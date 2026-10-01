# interface.ai CUA Take-Home — Buildout Plan

**Sources:**
- `/Users/akshithabedre/Desktop/interface.ai/artifacts/brief.md`: the assignment and the source of truth for scope, deliverables and evaluation criteria.
- `/Users/akshithabedre/Desktop/interface.ai/artifacts/plan_synthesis.md`: the current design and milestone proposal, synthesized from three agents (architecture, safety/HITL, build plan). Every "keep / cut / simplify" call below is made against this file.
- `/private/tmp/claude-501/bundled-skills/2.1.286/e28bafd4f275958007d1f65387041ddc/claude-api/shared/tool-use-concepts.md` §Computer Use and `.../shared/model-migration.md` §Migrating to Claude Opus 5.5 (cached 2026-09-25): I used these to verify the API facts in plan_synthesis. They hold up. `computer_toolset_20260801` is the only accepted computer tool on `claude-opus-5-5` (Claude API). It has no `name` and no display size. Each action arrives as a member `tool_use` block, possibly several in one turn, and every `tool_result` must echo `toolset_name:"computer"`. Forced `tool_choice` returns a 400. Thinking cannot be disabled and effort defaults to `medium`. History must be append-only.

**Context:** This is the buildout plan for the take-home. It answers *"in what order, with what gates, and with what cut, does one engineer ship this in ~36h?"*
**Provenance:** This is synthesized opinion that pressure-tests plan_synthesis.md. It is a recommendation, not an authoritative plan.
**Regime assumption:** One engineer, AI-assisted, 4–5 focused days (~36h core + ≤4h contingency), single process, single synthetic tenant. Multi-tenant and desktop support are **design-only** (brief §3.7). My normal multi-quarter method is compressed accordingly: milestones become phases measured in hours, and the team shape is one line.

---

## Framing correction (the lens)

This is not an agent-building problem. It is a **record/replay equivalence problem** with an LLM at the front. The LLM loop is the cheapest part to get running and the most expensive part to get *wrong in a way you discover late*. The load-bearing question is whether the element the model *meant* is the element the recorder *wrote down* and the element the replayer *will hit* on a different input. All three are resolved through a frameset with no IDs. The evaluators grade, in order: the schema, replay plus the error taxonomy, and the escalation/safety model. They explicitly penalize breadth. The word budget below follows those priorities. plan_synthesis.md is a strong design. Its failure risk is **volume, not direction**: the safety and HITL sections are specified at production depth, and the milestone hours don't fund that depth.

## Routing gaps in inputs

- **Unverified — I could not inspect the three raw specialist outputs behind plan_synthesis.md, only the synthesis.** So I can't check whether each agent stayed within its declared scope. What the synthesis does show is a **reconciliation gap**, not a routing gap. The safety/HITL content is written as a full spec: HMAC single-use tokens, a time-windowed network commit guard, hash-chained audit, human-step folding into draft revisions, a 25-item security test list. The build-plan content allots it M5 3h + M7 4h + M8 2.5h. Nobody pushed back on the gap. The cuts in §4 below are that pushback.
- The **API facts block** in plan_synthesis.md has no source cited. I verified it against the claude-api skill reference (Sources line). Treat it as confirmed as of 2026-09-25, and re-check the member tool names during spike S1.
- Nobody owned the **hostile target app as a product**. It is the surface every gate depends on, and its hostility level directly sets discovery difficulty. I've assigned it an owner and a layering rule (failure mode 8).

---

## 1. Build sequence — 5 phases, strict dependency order

**Phase 1's gate G3 is the proving milestone.** If G3 passes, everything after it is hardening and evidence. If it fails, no amount of HITL or safety polish saves the submission, because the brief's through-line ("model discovers → artifact → deterministic replay") isn't demonstrated.

### Phase 0 — Foundation + the two de-risking spikes (Day 1, h0–8)

> **Version-dependent:** the toolset facts were verified against the claude-api reference cached 2026-09-25. Confirm the exact member names that matter to us (`left_click`, `type`, `key`, `scroll`, `zoom`, `screenshot`) from the first live response in spike S1 before writing the dispatcher. Don't trust recall.

| Item | Owner | h | Notes |
|---|---|---|---|
| P0.1 Scaffold: uv, pyproject, Makefile, `.gitignore` (`.env`, `runs/`), `.env.example`, `docs/DECISIONS.md`, local `git init` | main | 1 | Set Typer `pretty_exceptions_show_locals=False` **now** (see failure mode 7). Add a structlog JSON pipeline with a stub redaction processor that fails closed. |
| P0.2 Static spike page `spike/frameset.html`: 2-level frameset, bordered frames, one scrolled frame, label-in-sibling-`<td>`, `<input type=image>` submit, no ids | main | 0.5 | Served by `python -m http.server`. This decouples the spike from the real target app. |
| **S1 spike: live toolset loop + hit-test through frames** | main | 3 | Real `claude-opus-5-5` with `computer_toolset_20260801`, 1280×800, `device_scale_factor=1`. Use `elementFromPoint` recursing through frames with offsets, then snap to the nearest interactive ancestor. Act **through the resolved element**. Save the raw responses to `fixtures/model_responses/spike.jsonl`. |
| Target app v1: login, frameset shell, member search (**POST**, deliberately), member detail, `seed.json` (100001–100020), `POST /__faults` (once/always/nth) | Lane A | (4) | Transfer screens are **templates only** on day 1. Hostility goes in layer 1 only (see failure mode 8). |
| Artifact schema v0 (the cut version, §2) + condition language + JSON-Schema snapshot test + a **hand-written** `member_inquiry@0.0.1` | Lane B | (3) | Main reviews and freezes it at G1. |
| Target resolver core: ranked strategies → unique-resolution check, **shared by recorder and replayer** | main | 2.5 | One module. Recorder and replayer must import the same resolver, or equivalence is unprovable. |

- **G0 (≈h5), spike gate, binary.** In a live 5–8 step run on `spike/frameset.html`, (a) zero API 400s across the run, including at least one turn with ≥2 batched member calls; (b) every `left_click` resolves to the element whose bounding box contains the click point, in the correct frame, including the scrolled frame; (c) a `type` after a click lands in the field that `activeElement`, recursed through frames, reports. **If G0 fails, stop.** Switch grounding to the pre-decided fallback (ratification item 1) before building anything else on top.
- **G1 (h8).** Schema frozen with its snapshot test committed. The hand-written artifact validates. A scripted Playwright smoke reads 100007's balance through the nested frames of the real target app.

### Phase 1 — Replay + discovery + compile → **G3: the proving milestone** (Day 2, h8–16)

| Item | Owner | h |
|---|---|---|
| Replay engine on the hand-written artifact: resolve → act → race post-condition vs timeout (never fixed sleeps) → extract outputs → identity-checked checkpoint → discriminated-union result | Lane A | (4) |
| Discovery loop, built on the spike: member-call dispatcher, batch staleness rule, custom `strict` tools (`declare_input`, `record_output`, `assert_checkpoint`, `report_outcome`, `request_human`, `goal_complete`, `type_secret`), stop conditions, `ScriptedModelClient`, append-only history | main | 3 |
| Recorder: per act, write multi-strategy candidates, each validated by the shared resolver to uniquely hit the acted element. `record_output` value **verified against the DOM text** at the resolved element | main | 1.5 |
| Compiler v0: drop failed/no-op acts → cut revisit loops → collapse retyping → parameterize values equal to declared inputs → literal deny-by-default → post-conditions → self-replay on original + second input | main | 2.5 |
| S2 spike: HITL seam in isolation (headed Chromium, pause the coroutine, terminal "take/return control" via `asyncio.to_thread`, context-level init script captures input in a nested frame, resume) | Lane C | (1.5) |
| Proving run + fixes | main | 1 |

- **G2 (≈h12).** `uv run cua replay capabilities/member_inquiry/0.0.1.yaml -p member_number=100012 --json` returns `succeeded` with 100012's seeded outputs.

**G3 — PROVING MILESTONE. Target h16. Hard deadline h24; the cut list fires if it's missed.**

```bash
make target-app            # uvicorn target_app.app:app --port 8800 (separate shell)
uv run cua discover --policy policies/corebank-local.yaml --entry http://127.0.0.1:8800/ \
  --capability member_inquiry \
  --goal "Look up member 100007 and read their current savings balance and member status"
uv run cua compile runs/<run_id> --out capabilities/member_inquiry/0.1.0.yaml
uv run cua replay capabilities/member_inquiry/0.1.0.yaml -p member_number=100012 --json
uv run cua replay capabilities/member_inquiry/0.1.0.yaml -p member_number=999999 --json
uv run python scripts/check_proving.py runs/<run_id> capabilities/member_inquiry/0.1.0.yaml
```

`check_proving.py` passes only if **all** of the following are true:
1. The discovery run used the live `claude-opus-5-5` with `computer_toolset_20260801`. `model_responses.jsonl` is non-empty. The run ended via `goal_complete` in ≤40 steps.
2. The compiled artifact validates against the frozen JSON Schema. It contains **zero coordinates**. It contains **zero occurrences of `100007`** (parameterized to `{{member_number}}`, including in the checkpoint identity check). Every step's top-ranked strategy is non-visual and resolved uniquely at record time.
3. `outputs.savings_balance` (decimal) and `outputs.member_status` exist. The model-reported value equaled the DOM extraction at compile time.
4. Replay with **100012**, a *different* member, returns `succeeded` with outputs equal to `seed.json[100012]`, not 100007's values. It does so **3/3 consecutive times**.
5. Replay with **999999** returns anything **except** `succeeded`. Proper `business_outcome` classification is G4's job. A false `succeeded` here means the checkpoint is too weak, and that is a G3 failure.
6. `tests/test_architecture.py` passes. It asserts that `cua.replay` imports nothing from `anthropic` and that `cua.discovery` is not reachable from the replay entry point. "Model_calls=0" is enforced by the import graph, not by a counter.

**What G3 proves:** the thesis, end to end, with a parameterized input generalizing past the recorded value. **What it does NOT prove:** the error taxonomy, recovery, HITL, risky-action handling, or redaction completeness.

### Phase 2 — Robustness + safety (Day 3, h16–24)

| Item | Owner | h |
|---|---|---|
| Vendor detector library (`library/corebank.yaml`: session_expired, system_notice interstitial, http500/app_error, permission_denied) + handlers (Dismiss/Relogin/Backoff → resume/retry/restart_entry), per-detector `max_attempts`, run recovery budget 5, no-progress guard; `commit_irreversible` never auto-retried | Lane A | (4) |
| Fault-matrix integration tests, offline, against the target app | Lane A | (incl.) |
| Business outcome by **probe discovery**: a live discovery run on 999999 in which the model calls `report_outcome`. The compiler merges it as a `TextPresent` detector armed at the matching step, and accepts it **only if** the text is visible in the probe state and absent from every happy-path state in the trace (negative control) | main | 2.5 |
| `relabel` fault (renames a label) to show strategy fallback: the `attr` strategy wins, the trace records a soft-drift flag. Gives REPORT §4 real evidence for ~1h | main | 1 |
| Policy YAML + the single `act()` choke point (allowlist: origin/route/scheme/action-type; risk = max of action/element text/route/artifact annotation; artifacts may only raise risk) + `context.route` off-origin and scheme blocks | Lane B | (3) |
| Redaction: known-values registry → sensitive keys → patterns (SSN, Luhn PAN, 8–17 digit acct, DOB, email, phone), fail-closed; masked failure screenshots per frame; canary test | Lane B | (incl.) |
| Thinking summaries as the "why" log (see failure mode 2c), redacted | main | 0.5 |
| Integrate lanes, review, `security-auditor` pass | main | 3 |

- **G4.** Offline `pytest -m integration` fault matrix is green: `999999 → business_outcome(member_not_found)`; `interstitial+slow → succeeded (recoveries=2)`; `session_expire → succeeded after relogin`; `http500 → failed(app_error)` with a failure bundle; `relabel → succeeded` with a soft-drift flag; `permission_denied → escalated`.
- **G5.** The canary test greps `runs/ evidence/ capabilities/ *.log` for the seeded password, SSNs, DOBs and full account numbers. **Zero hits.** Policy tests are green: off-origin blocked, `javascript:` navigate blocked, a read_only goal can't commit, `key Return` on a form is classified commit-capable.

### Phase 3 — HITL on the live session + risky flow (Day 4, h24–32)

| Item | Owner | h |
|---|---|---|
| Control lease `{run_id, state, holder, epoch, intervention_id}`; `act()` checks the epoch under an `asyncio.Lock` both before resolve and immediately before the Playwright call; terminal operator is authoritative (`take` / `approve-once` / `deny` / `abort` / Enter-to-return, `--operator`); in-page banner; human-action capture in all frames (no password values); InterventionRequest written; resume at the **first unsatisfied step** computed from post-conditions, not a stored index; discovery resume = append a `tool_result` for the pending call plus a fresh screenshot and a redacted human-action summary | main | 4 |
| `ScriptedHuman` driver for a reproducible handoff test | main | 1 |
| Transfer flow: discovery reaches Confirm → policy ESCALATE → human `approve-once` (exact action) → receipt. `cua approve` writes a single-use approval record bound to `(capability, version, effective_sha256, params_hash, exp)`. Replay preflight returns `blocked_pending_approval` before launching the browser and re-checks at the commit step | Lane A | (3) |
| Evidence script: offline regeneration of all replay runs + `evidence/INDEX.md` (requirement → file) | Lane B | (2) |
| `review-flyswatter` pass with the override (see §8) | main | 2 |

- **G6.** `pytest tests/integration/test_handoff.py` passes. With ScriptedHuman: permission_denied → escalated → human completes the step on **the same `Page` object** (assert `id(page)` and the context cookie are unchanged) → hand back → revalidate → `succeeded`, and `human_actions.jsonl` is written. A stale-epoch `act()` raises `ControlLost`.
- **G7.** Transfer replay without an approval record → `blocked_pending_approval`. With one → receipt `TRN-xxxxxx`. A second use of the same record → `blocked_pending_approval`.

### Phase 4 — Evidence + communication (Day 5, h32–36, + ≤4h contingency)

Capture the live evidence (01 discovery lookup, 02 discovery transfer with approval, 07 live human handoff). Write REPORT.md under the exact 7 headings and README.md with the exact demo commands. Fix review findings. **Stretch work starts only if G0–G7 are green before h34.** Assume the stretch budget is spent on overrun. That is what it's really for.

### The non-obvious sequencing call

plan_synthesis.md lists the riskiest item (M3, coordinate→element resolution + toolset protocol) as its first named risk. It then schedules M3 **after 7.5h of scaffold, target app and replay work**. The temptation is to build the comfortable things first, because they're visible and testable. Resist it. The 3h S1 spike on a *static* frameset page goes on day 1 morning, before the real target app exists. A G0 failure on day 1 costs 3h. On day 2 it costs the schema, the recorder and the compiler.

The second call is to **keep** plan_synthesis's choice of replay on a hand-written artifact (Lane A, G2) **in parallel** with the discovery loop, not after it. That decouples "is the replay engine right" from "is the compiler right" and gives G3 a known-good comparison artifact.

---

## 2. The artifact and replay contract — where the grade is decided

The schema in plan_synthesis.md is the right *shape* and roughly 30% too *wide* for 36h. Every field below must be justified in REPORT §2, and an unjustifiable field costs credibility. Cut to this:

| Keep in v0 (built + tested) | Design-only (REPORT §4/§7, not code) | Cut entirely |
|---|---|---|
| `schema_version`, `id`, `semver`, `status: draft\|approved` | `status: suspect\|deprecated` lifecycle + drift K-of-N | `quorum`, `min_confidence` per step |
| `summary` (agent-facing tool description incl. outcomes), `app` binding (vendor/product/version_range/surface) | Base → product-version patch → tenant overlay ops keyed by stable step ids | Per-step `page_signature` in provenance (keep one on the checkpoint only) |
| `side_effects` (= max step risk), `labels` (`$labels.key`), `allowed_literals` | Desktop UIA/AX and pixel surfaces (surface table) | Detector `origin: explored` + separate `explore.py` LLM classifier |
| `inputs` / `outputs` (typed, `pattern`, `sensitivity`, extraction + transforms) | LLM-seeded rediscovery diff on hard drift | `FieldValueEquals` condition (use `TextPresent` + scoped `ElementResolvable`) |
| `outcomes` (closed set), `entry` (route, login script ref, entry condition) | Tenant B skin app | |
| `steps[]`: stable `id`, `intent`, `action`, `target` (frame path + ranked strategies + `expect` text guard), `value` template, `risk`, `post` + timeout, `idempotent` | | |
| `detectors[]`: kind (`recoverable\|hard_failure\|escalate\|business_outcome`), condition, armed steps, priority, handler, `max_attempts`, `origin: library\|discovered\|human` | | |
| `checkpoint` (incl. identity check: input id visible on the result), `provenance` (run_id, model, transcript sha, compiler version), `review` (approver, sha256) | | |
| Conditions: `TextPresent` (visible + frame-scoped), `ElementResolvable`, `LocationMatches`, `OutputsPresent`, `All/Any/Not` | | |

**Result contract:** keep plan_synthesis's discriminated union as written (`succeeded` / `business_outcome` / `failed{code,…}` / `escalated` / `blocked_pending_approval`, plus `side_effects_committed`). It's the most defensible artifact in the synthesis. One change: `failed.code` should start with the 7 codes the fault matrix actually exercises (`target_unresolved`, `postcondition_timeout`, `checkpoint_mismatch`, `app_error`, `recovery_exhausted`, `policy_denied`, `outcome_unknown`). Add the others only when a test produces them. An enum value no test produces is a claim you can't defend.

Route the frozen v0 schema plus the result contract through `backend-architect` once, at G1 (§8). Don't iterate the schema by committee after G1.

## 3. Per-surface build — the two hard pieces

1. **Targeting (hittest + resolver).** Hardest, and main-thread only. The equivalence invariant: *discovery executes the action through the same resolved element handle that the recorder serializes, and the replayer resolves the serialized target with the same resolver code.* Raw-coordinate clicking during discovery is forbidden once G0 passes. It is the one path where what was recorded and what happened can silently diverge.
2. **The toolset dispatcher.** Second hardest, because of batch actions and the "no forced tool_choice" rule. A model that ends its turn with prose instead of `goal_complete` gets one appended nudge (a user turn) and is then stopped as `dead_end`. It is never "retried" by editing history.
3. Everything else (replay waits, handlers, policy, redaction) follows ordinary patterns and parallelizes well across lanes.

## 4. Where I disagree with plan_synthesis.md

**Mis-ordered**
1. **The proving milestone is unnamed and its gate is too weak.** M4's "discover → compile → replay with model_calls=0" passes if you replay the *same* member. It also passes if 999999 returns `succeeded` with a blank balance. Replace it with G3: a different input, 3/3 runs, 999999 ≠ succeeded, and an import-graph check.
2. **The riskiest spike sits after 7.5h of safe work** (M0→M1→M2→M3). Move a 3h S1 to day 1 on a static page (see §1 "non-obvious sequencing call").
3. **HITL is split into M5 (3h) + M8 (2.5h) with the error taxonomy (M6) in between.** Run a 1.5h isolated S2 spike on day 2 (Lane C) to de-risk the seam early. Then build HITL once, in Phase 3, on top of real detectors that produce `escalate`. Don't build it twice.

**Over-built for the time box (cut or simplify)**
4. **HMAC single-use tokens + a separate `approve-run` command.** HMAC adds forgery resistance against an attacker who already has your filesystem. Keep the *binding semantics* (capability, version, sha256, params_hash, expiry, single use) in a plain approval record that replay consumes. That saves about 1.5h, and the REPORT argument stays identical.
5. **Network commit guard with a ~3s grant window after an approved act.** This one is wrong for the target domain, not just over-built. Legacy apps POST for *reads*: search forms, postbacks, frame navigation. A time-windowed POST blocker will either false-positive on the member search or race on slow commits. Replace it with an off-origin/scheme block at `context.route` (keep) plus a **route-scoped commit deny list** from policy (`/txn/post`) that opens only under a consumed approval. Make the target app's member search a POST on purpose, so a test proves the classifier doesn't conflate POST with commit.
6. **`explore.py`, a separate LLM classification pass over probe-input divergences.** Replace it with a second **real discovery run** on the probe input, in which the model calls `report_outcome`. Same evidence value, one fewer pipeline, and it strengthens "the model discovers" for the error path. Keep the negative-control acceptance rule. Fallback if time runs short: a reviewer-authored detector with `origin: human` (the brief allows clean seams).
7. **M8 "fold human steps as a draft revision (origin: human)".** Cut to design-only. The brief requires *recording* what the human did (`human_actions.jsonl` + intervention record), not compiling it.
8. **Schema width:** quorum, min_confidence, per-step page signatures, overlay.py code, `FieldValueEquals` (see the §2 table).
9. **Evidence runs 9 → 8.** Merge 05 (interstitial+slow) and 06 (session_expire) into one recoverable run with three recoveries. Add the `relabel` soft-drift run, which is cheap and feeds REPORT §4.
10. **`clear_tool_uses_20250919` context editing.** Don't use it. 40 steps × one 1280×800 screenshot fits comfortably in 1M context, and cost isn't a constraint. Every beta header is another protocol surface to debug. Append-only, no pruning, no editing.

**Missing**
11. **The record/replay equivalence invariant is implied but not stated or tested.** It needs a test that runs discovery via `ScriptedModelClient` on fixtures, then asserts that for every recorded step the resolver output equals the element handle actually acted on.
12. **Output value verification.** The model reads the balance from a *screenshot*. The compiler must assert that the DOM extraction at the resolved output target equals the model's claimed value, normalized. Otherwise you have an artifact that extracts the wrong cell, and you discover it only on a member whose adjacent cell differs.
13. **Batch-action staleness.** Several member calls per turn are computed from *one* screenshot. If action 1 navigates or changes the frame DOM, the coordinates in action 2 are stale. Rule: after each executed member call, compare a cheap state signature (URL of every frame + DOM node count). If it changed, return `is_error` tool_results ("screen changed; re-observe") for the remaining calls. Every `tool_use` still gets its result, each with `toolset_name:"computer"`.
14. **The "why" log.** The brief requires "what the agent did **and why**". Custom tools carry `rationale`, but toolset member calls (`left_click`, `type`) have no rationale field, and on Opus 5.5 thinking `display` defaults to `omitted` (empty). Set `thinking: {type: "adaptive", display: "summarized"}` and log the summary preceding each action through the redactor. Without this, the discovery log is a click list with no reasons.
15. **Evidence regeneration policy.** `make evidence` must regenerate **replay** runs offline and deterministically. Live discovery runs (01, 02, 07) are **captured once** with `make evidence-live` and committed. Otherwise every docs tweak re-runs nondeterministic discovery, the evidence drifts from the REPORT text, and you lose an hour on day 5.
16. **Effort.** plan_synthesis says "set effort explicitly" but doesn't pick a level. Pick `high` for discovery (intelligence-sensitive, cost unconstrained). The single-shot compile-time call doesn't exist in this plan, because item 6 removed it.

## 5. Observability and evals

The skeleton is one `runs/<run_id>/` per run, containing:
- `events.jsonl` (redacted; one event per observe/decide/act/detector/recovery/lease change)
- `model_responses.jsonl` (discovery only; response content blocks; **request images are never written**)
- `trace.json` (strategy used, confidence, recoveries, duration per step)
- `failure/` bundle: masked screenshot per frame, redacted DOM snapshot of the failing frame, `expected` vs `observed`.

Playwright tracing stays **off**, because traces capture network bodies, including the login POST. There's no eval program to design here. "Multi-run stability" is the 3/3 clause in G3, so `ml-expert` isn't on the critical path (§8).

## 6. The hard parts — failure modes that actually kill this submission

Ranked by blast radius. Each one names the earliest spike that de-risks it.

### 1. Coordinate→element resolution is wrong through framesets
**Trigger:** frame offsets ignore frame borders or scroll; `elementFromPoint` returns a `<td>`, `<font>` or `<img>` inside the real control; the hit lands on a hidden duplicate Submit; DPR ≠ 1.
**Blast:** the artifact records the wrong control. Replay is then *deterministically wrong*, the worst outcome, because it looks like success.
**Mitigation:** run hit-test JS per frame with a cumulative `getBoundingClientRect` + `clientLeft/Top` + scroll offset. Snap to the nearest interactive ancestor (`a, button, input, select, textarea, [onclick], [role]`) and require it to be **visible and topmost** (re-check `elementFromPoint` at the snapped element's center). Assert the screenshot size equals the 1280×800 viewport on every observe. Table-driven unit tests on `spike/frameset.html` with known coordinates, including the scrolled frame. Plus the equivalence test (§4 item 11).
**Earliest spike:** S1, day 1.

### 2. Computer-toolset protocol details on `claude-opus-5-5`
**Trigger:**
- (a) a `tool_result` missing `toolset_name:"computer"` returns a 400 mid-run;
- (b) stale batched coordinates (§4 item 13);
- (c) empty thinking means no "why" (§4 item 14);
- (d) `type` with no preceding click targets whatever has focus, and top-level `document.activeElement` is the `<frame>` element itself;
- (e) a `key` member pressing Return in a field triggers an implicit form submit, i.e. an unclassified commit;
- (f) `zoom` results in a mental coordinate-space mismatch (coordinates stay in full-screenshot space);
- (g) `stop_reason == "refusal"`;
- (h) the model ends with prose because `tool_choice` can't be forced.

**Blast:** the discovery run dies or records garbage. With (e), the system commits without approval.
**Mitigation:** a dispatcher keyed on block `name`, with an exhaustive `match` and unknown members → `is_error`. `activeElement` is resolved by recursing into `contentDocument`. `key` with Return/Enter is classified as `commit`-capable when the focused element is inside a `<form>` whose action route isn't read-only in policy. Refusal maps to `escalated(kind=refusal)`, and **no `fallbacks`** (ratification 4). One nudge on prose-only end_turn, then `dead_end`. Conformance tests replay the S1 fixture through `ScriptedModelClient`, including a recorded batch turn.
**Earliest spike:** S1, day 1.

### 3. The compiler keeps exploratory actions or mis-parameterizes
**Trigger:** the model opens the wrong menu and backs out; types, clears, retypes; reads the balance from the wrong cell in the image. `100007` coincidentally equals another literal. The checkpoint text "Member 100007" stays a literal.
**Blast:** the artifact replays on 100007 and fails or lies on 100012.
**Mitigation:** prune rules (failed/no-op = no frame-URL or DOM-signature change; cut revisit loops by (location, signature)). Any non-allowlisted literal fails the compile. The model-claimed value is checked against DOM extraction (§4 item 12). **Self-replay on a second seeded member with known ground truth is part of compile**, and a failure keeps `status: draft`. Golden-file compile test from the recorded trace fixture.
**Earliest spike:** G3, day 2. The probe discovery run on day 3 re-tests it.

### 4. Append-only history violations
**Trigger:** "helpful" cleanup that drops old screenshots or rewrites a turn. Injecting the HITL human-action summary by *editing* a pending turn instead of answering the pending `tool_use`.
**Blast:** 400s or invalidated thinking mid-discovery, typically during the live HITL evidence run, the hardest one to re-capture.
**Mitigation:** `messages` is an append-only wrapper type with no `__setitem__`/`pop`. A test asserts that the serialized prefix of turn N is a byte-prefix of turn N+1 across a fixture run that includes a handoff. Discovery resume answers the pending `tool_use` with a `tool_result` ("operator took control; summary: …" + fresh screenshot).
**Earliest spike:** S1 (structure), S2 (handoff shape).

### 5. Detector false positives and races
**Trigger:** "NO RECORD FOUND" exists hidden in every page's DOM (common in legacy templates). Static help text contains "error". The post-condition and a detector are true simultaneously. A slow load reads as `postcondition_timeout`.
**Blast:** a legitimate member is reported `member_not_found`, a business-wrong answer with a clean status.
**Mitigation:** `TextPresent` means *visible* and *frame-scoped*. Business-outcome detectors are accepted only if they are false on every happy-path trace state (negative control, in compile). Fixed priority: `hard_failure > escalate > business_outcome > recoverable > post-condition`. Waits use `asyncio.wait(FIRST_COMPLETED)` over post-condition/detector/timeout pollers, never `sleep`. The target app ships a hidden `NO RECORD FOUND` div on the happy page **on purpose**, so the test is real.
**Earliest spike:** Phase 2 hour 1, day 3.

### 6. Handoff races and seam bugs
**Trigger:**
- an automation `act()` is in flight when the human takes control;
- the human navigates or logs out;
- a double Enter / double resume;
- blocking `input()` on the asyncio loop freezes Playwright event processing, so the `expose_binding` callbacks from the human's clicks never fire;
- init-script capture is lost on frame navigation;
- the human performs an irreversible action.

**Blast:** a "real handoff" that is actually a fresh session or a frozen browser fails a must-have requirement outright. A post-resume step against a moved page means a wrong action.
**Mitigation:** an epoch check under the lock at two points in `act()`. Terminal I/O via `asyncio.to_thread`. A **context-level** init script, which re-runs in every frame on every navigation. Revalidation on resume: single page, on an allowed origin, not on login (else scripted relogin), then the first unsatisfied step. Human-performed actions on commit routes set `side_effects_committed=possible`. Unanswered interventions abort after a 15-minute TTL. The G6 test asserts the same `Page` object.
**Earliest spike:** S2, day 2 (Lane C).

### 7. Redaction gaps
**Trigger:**
- Typer's default `pretty_exceptions_show_locals=True` prints function locals (password, params) on any crash;
- raw request logging persists base64 screenshots;
- Playwright traces contain the login POST body;
- thinking summaries quote PII;
- `mask=` locators don't cover elements inside frames;
- failure DOM snapshots include the SSN cell.

**Blast:** "never persist sensitive data" is violated inside the submitted evidence, in front of a bank-domain evaluator.
**Mitigation:** show_locals off from P0.1. Request images are never written; only response content is. Tracing is off. The thinking summary goes through the same fail-closed processor. Masks are applied per frame with frame-scoped locators, and a test asserts the masked region's pixels equal the mask color. The DOM snapshot is redacted by the pattern pass. The canary at G5 greps every output root, and `make evidence` runs it last and fails the build on any hit. REPORT §6 states plainly that screenshots *to the model provider* are a data flow (synthetic data here; production needs ZDR + DPA).
**Earliest spike:** P0.1 (show_locals + processor), day 1. Canary on day 3.

### 8. (Not fatal but expensive) Target-app hostility and scope creep
**Trigger:** the target app is made so hostile on day 1 that discovery can't finish, and hours go into prompt-tuning. Or the transfer flow, tenant B and the catalog all get started.
**Mitigation:** add hostility in layers. Layer 1 (frameset, no ids, label-in-sibling-td, POST search) must pass G3 before layer 2 is added (duplicate hidden Submit, `<input type=image>`, `href="javascript:"`, generated class names). Each layer is a fault-controller flag, so it's demonstrable in evidence. The transfer flow's minimum is G7. Its cut path is in §7.

## 7. Timeline

**~36 focused hours is the floor for this slice, not a comfortable estimate.** Anyone quoting 2–3 days for the full vertical slice is descoping. The usual hidden cuts are discovery that is scripted rather than live, "handoff" to a fresh browser rather than the live session, or a happy-path-only replay. Each of those fails a must-have requirement. The ≤4h stretch is the contingency for overrun. Plan on delivering zero stretch.

| Day | Hours | Main thread | Parallel lanes | Gate |
|---|---|---|---|---|
| 1 | h0–8 | P0.1 scaffold → spike page → **S1** → schema freeze → resolver | A: target app v1 · B: schema v0 + conditions + hand-written artifact | G0 (≈h5), G1 (h8) |
| 2 | h8–16 | discovery loop → recorder → compiler → **proving run** | A: replay engine (G2) · C: **S2** HITL spike | **G3 PROVING (h16; hard deadline h24)** |
| 3 | h16–24 | probe discovery (business outcome) → relabel drift → "why" log → integrate → security-auditor | A: detectors/handlers + fault matrix · B: policy/act()/redaction/canary | G4, G5 |
| 4 | h24–32 | HITL integration + ScriptedHuman → review-flyswatter | A: transfer + approval record + preflight · B: evidence script + INDEX | G6, G7 |
| 5 | h32–36 (+≤4) | live evidence capture (01, 02, 07) → REPORT → README → fixes | — | all evidence present; canary green |

**Honest checkpoint:** if G3 isn't green by h24, the problem is not "more parallel agents". It's targeting (failure mode 1) or the dispatcher (failure mode 2). Fire this cut list, in order:
1. Transfer flow drops to *policy-gated discovery only*: the model reaches Confirm, policy escalates, the human denies, evidence is captured. Replay approval is covered by unit tests only.
2. The `relabel` drift run.
3. Probe discovery is replaced by a reviewer-authored `business_outcome` detector (`origin: human`).
4. The in-page banner goes; the terminal stays.
5. `mypy --strict` goes.

**Never cut:** live discovery, artifact + replay on a different input, the 3-way taxonomy, live-session handoff, allowlist, redaction + canary.

**Team:** one engineer with three AI coding lanes. The engineer owns every decision and writes the targeting core, the dispatcher, the compiler and REPORT.md.

## What NOT to build

- **A tenant overlay engine (`overlay.py`), a tenant B skin app, drift K-of-N state machine.** Evaluators explicitly don't reward multi-tenant plumbing. REPORT §4 gets the design, plus the one real `relabel` fallback run as evidence that the seam exists.
- **An operator web console or co-browsing UI.** The brief scopes it out. The terminal is the authoritative control channel; the in-page banner is convenience only.
- **A capability catalog or tool interface, codegen, LLM-assisted single-step fallback on replay.** The stretch list allows one or two. The time box funds zero, and an LLM fallback in replay muddies the "no model in the loop" proof.
- **A desktop surface.** The `Surface`/`Actuator` Protocols in `surface/base.py` plus the REPORT surface table are the deliverable.
- **HMAC tokens, hash-chained audit, a time-windowed network commit guard.** See §4 items 4–5. Plain append-only `audit.jsonl` is enough.
- **Playwright traces as evidence.** They persist network bodies.
- **Docker, CI, queues, a service split.** Single process, `uv run`, `make`.

## Open decisions for sponsor ratification

1. **Grounding = pure computer toolset (screenshot + coordinates) with hit-test→element, not a DOM-ref custom tool.** This fits the brief's "bias toward no clean DOM". *Reversal cost:* about 4h if G0 fails. The fallback is pre-decided: keep the toolset for perception, and add a numbered element list plus a `strict` `act_on(ref, action)` custom tool, with the recorder unchanged downstream of the resolver.
2. **Discovery acts through the resolved element, never the raw coordinate.** *Reversal cost:* none to keep. Reversing it voids the equivalence guarantee.
3. **`effort: high` + `display: "summarized"` thinking for discovery.** *Reversal cost:* trivial (config). Lowering effort risks more dead-ends.
4. **No server-side refusal `fallbacks`; refusal → escalate.** A mid-run model switch changes provenance and drops thinking continuity. *Reversal cost:* 30 min, but provenance must then record the per-turn model.
5. **No context editing or pruning; append-only for the whole run.** *Reversal cost:* low, unless runs exceed ~150 steps, which the 40-step cap prevents.
6. **Business outcomes discovered by a second live run on a probe input, not a separate LLM classifier pass.** *Reversal cost:* 1h to fall back to a reviewer-authored detector.
7. **Approval = a bound single-use record, no HMAC.** *Reversal cost:* about 1h to add signing if a reviewer insists.
8. **Route-scoped commit deny list instead of a time-windowed POST guard.** *Reversal cost:* about 2h, plus the false-positive risk on legacy POST reads comes back.
9. **Transfer flow minimum = discovery approval gate + replay preflight/approved path.** *Reversal cost:* scope only.
10. **Discovery evidence captured once and committed; only replay evidence is regenerated.** *Reversal cost:* none, but regenerating means non-reproducible docs.
11. **G3 includes "999999 ≠ succeeded" and "replay imports no `anthropic`".** This makes the proving gate stricter than plan_synthesis's M4. *Reversal cost:* none; it only catches problems earlier.
12. **YAML for review + canonical JSON for `content_sha256`** (kept from plan_synthesis). *Reversal cost:* low.

## 8. Specialist routing (during the build)

**Override preamble.** Paste this verbatim at the top of every `simpleplanner-backend` / `simplecoder-backend` / `review-flyswatter` invocation:
> "Greenfield project at /Users/akshithabedre/Desktop/interface.ai — NOT DartIQ. Ignore all DartIQ conventions: no MongoDB/Motor, no ApiResponse envelope, no RequireMSPUser/TenantDB, no Jira, no DartIQ commit scopes, no pip — use uv. Stack: Python 3.12, Pydantic v2, Playwright async, pytest, Typer (pretty_exceptions_show_locals=False), structlog JSON with a fail-closed redaction processor. Never push or create anything on GitHub. Single process, asyncio, no services."

| Work | Agent | When | Seed prompt |
|---|---|---|---|
| Target app v1 + fault controller (Lane A, day 1) | `fastapi-pro` (no DartIQ baggage; better fit than simplecoder-backend for a Jinja app) | Day 1 | "Build `target_app/` (FastAPI + Jinja, port 8800): a deliberately hostile legacy 'core banking' UI. Layer 1 only: login (scripted creds from .env), 2-level frameset shell, member search as an HTML **POST** form, member detail in nested tables with labels in sibling `<td>` (no `for=`), no ids/test-ids, a hidden `NO RECORD FOUND` div present on the happy page, `seed.json` members 100001–100020 with SSNs in 9xx range displayed masked, `POST /__faults` (modes once/always/nth; faults: interstitial, slow, session_expire, http500, permission_denied, relabel). Transfer screens as templates only. Acceptance: scripted Playwright smoke reads 100007's balance through frames." |
| Schema v0, conditions, replay engine, policy, redaction, evidence script (Lanes A/B) | `simpleplanner-backend` → `simplecoder-backend`, **with the override** | Days 1–4 | Per-story: paste the story + acceptance from §9 + the §2 keep table. "Plan file-by-file under `src/cua/<pkg>/`, then implement test-first." |
| Freeze review of schema + result contract | `backend-architect` | G1 (end of day 1), once | "Review `src/cua/artifact/schema.py` and `replay/result.py` as an agent-invocable capability contract. Questions: is every field defensible for a 1–3 page write-up; is the result union unambiguous for a calling agent; does anything paint the design into a corner for desktop surfaces or tenant overlays keyed by stable step ids? Recommend removals before additions." |
| Security pass on act()/policy/redaction/approval/injection | `security-auditor` | End of day 3; re-run on the transfer diff on day 4 | "Audit the single `act()` choke point, `policies/corebank-local.yaml`, the redaction processor, failure-bundle masking inside framesets, approval-record binding/single-use, and prompt-injection via on-screen text (can page text widen allowed actions or routes?). Synthetic data only. Report exploitable sequences, not checklists." |
| Pre-submit review | `review-flyswatter`, **with the override**; ignore the MongoDB/Temporal/Redis/DSPy-specific findings from review-data/review-shelving | End of day 4 | "Review the full repo diff. Priority: replay correctness under faults, handoff races (epoch/lock), compiler parameterization, redaction coverage. Treat any DartIQ-convention finding as N/A." |
| Discovery prompt + toolset loop code | **main thread, with the `claude-api` skill loaded** (not a subagent) | Day 1–2 | n/a. The skill is authoritative for the toolset wire format; recall is stale. |
| `ml-expert` | **Not on the critical path.** Nothing here is ML methodology. Prompt and loop design is agent engineering. Route only if a stretch multi-run stability study is attempted: "Design a minimal N-run stability measurement for deterministic replay of a compiled UI capability across 20 seeded inputs and 3 fault modes; what metrics distinguish locator fragility from detector false positives?" | Stretch only | — |

**Do NOT delegate:**
- the hit-test/resolver core and the equivalence test;
- the toolset dispatcher;
- the compiler's prune/parameterize rules;
- the schema freeze decision;
- the error-taxonomy priority order;
- the control-transfer state machine;
- live evidence capture;
- REPORT.md.

The brief requires the candidate to "explain and defend every part". These are the parts an evaluator will probe. Agent-written REPORT prose is detectable and indefensible under questioning.

## 9. Recommended epic/story outline (input to epic-writer)

**E1 Foundation & de-risking**
- **S1 Scaffold & repo hygiene.** uv project, Makefile, `.gitignore`, `.env.example`, DECISIONS.md, structlog + fail-closed redaction stub, Typer show_locals off. *AC:* `make test` green; `uv run cua --help`; a crash test shows no locals in output.
- **S2 Hostile target app, layer 1.** Login, frameset, POST member search, detail, seed, fault controller. *AC:* scripted Playwright smoke reads 100007's balance through nested frames; every fault mode is toggleable via `POST /__faults`.
- **S3 Toolset + hit-test spike (G0).** Live 5–8 step run on the static frameset page; recorded fixture. *AC:* zero 400s including one batched turn; all clicks resolve to the containing, topmost interactive element in the correct frame (incl. the scrolled frame); `type` targets `activeElement` across frames.

**E2 Capability artifact & replay**
- **S4 Artifact schema v0 + condition language.** The §2 keep-set; YAML ↔ canonical JSON; sha256. *AC:* JSON-Schema snapshot test; round-trip test; hand-written `member_inquiry@0.0.1` validates; coordinates rejected by the validator.
- **S5 Shared target resolver.** Ranked strategies (attr, role+name, label anchor + relation, table_cell row×col, text, anchored structural, visual-last); uniqueness check. *AC:* table-driven tests on fixture pages; ambiguity returns `target_unresolved`, never first-match.
- **S6 Replay engine + result contract (G2).** Waits race post-condition/detectors/timeout; outputs; identity checkpoint; discriminated union. *AC:* hand-written artifact replays 100012 → `succeeded` with seeded outputs; no `sleep` in `replay/`; `replay` imports no `anthropic`.

**E3 Discovery & compile (proving)**
- **S7 Discovery loop.** Dispatcher on member names, batch staleness rule, strict custom tools, stop conditions, refusal → escalate, append-only history, summarized-thinking "why" log, ScriptedModelClient. *AC:* fixture replay passes offline; append-only prefix test; prose-only end_turn → one nudge → `dead_end`.
- **S8 Recorder with equivalence + output verification.** *AC:* for every recorded step, the resolved candidate equals the acted element handle; a `record_output` mismatch vs DOM fails the recording.
- **S9 Compiler + self-replay (G3 PROVING).** *AC:* `scripts/check_proving.py` passes all 6 G3 clauses on a live discovery run.

**E4 Robustness**
- **S10 Detector library + recovery handlers + fault matrix (G4).** *AC:* offline integration tests: interstitial+slow+session_expire → `succeeded` with recoveries; http500 → `failed(app_error)` with failure bundle; `commit_irreversible` never retried; recovery budget enforced.
- **S11 Probe discovery for business outcomes + relabel drift.** *AC:* 999999 → `business_outcome(member_not_found)`; the detector passes the negative control against the hidden-div happy page; relabel → `succeeded` with a soft-drift flag in the trace.

**E5 Safety**
- **S12 Policy + act() choke point + approval gate (G7).** *AC:* off-origin and `javascript:` blocked; POST member search allowed; Return-in-form classified commit-capable; read_only goal can't commit; transfer replay without a record → `blocked_pending_approval`, with one → receipt, reused record → blocked.
- **S13 Redaction pipeline + canary (G5).** *AC:* canary greps all output roots for seeded password/SSN/DOB/acct → zero hits; masked-region pixel test inside frames; Luhn/pattern unit tests.

**E6 Human-in-the-loop**
- **S14 Control lease + terminal operator + live-session handoff (G6).** *AC:* ScriptedHuman test: escalate → human acts on the same `Page` → hand back → revalidate → resume at the first unsatisfied step → `succeeded`; stale epoch → `ControlLost`; `human_actions.jsonl` + InterventionRequest written; terminal I/O doesn't block the event loop (the binding fires during a pause).

**E7 Evidence & communication**
- **S15 Evidence script + INDEX.** *AC:* `make evidence` regenerates replay runs offline and runs the canary last; `make evidence-live` captures 01/02/07; INDEX.md maps each brief requirement → file.
- **S16 README + REPORT.** *AC:* README demo commands copy-paste and run from a clean clone (offline path documented); REPORT has exactly the 7 brief headings, is 1–3 pages, and §7 lists cuts + next steps.
