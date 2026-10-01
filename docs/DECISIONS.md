# Decision log (ADR-lite)

One entry per design choice: context, decision, alternatives considered, consequence. This is the crib sheet for defending the design in review — kept up to date as the build progresses, not written after the fact.

Standards followed: see `artifacts/adopted_standards.md` for the general Python/testing/security/git conventions this project holds itself to.

---

## D0 — Grounding: pure computer-use toolset, not a DOM-ref custom tool
**Context:** the brief asks for an approach that still works with no clean DOM (legacy web, desktop).
**Decision:** discovery perceives via screenshots + coordinates (`computer_toolset_20260801` on `claude-opus-5-5`), with a compact on-screen element list sent alongside each screenshot as a grounding aid only — the model still acts by coordinate, never by element reference.
**Alternatives:** a custom `act_on(element_ref, action)` tool keyed to DOM/AX nodes — rejected as the primary channel because it silently assumes a clean, queryable tree, which legacy apps and canvases don't have.
**Consequence:** every click must be resolved to a real element *after* the model acts, via hit-testing (see D1) — coordinates never make it into the artifact.
**Reversal cost:** ~4h if the G0 spike shows this doesn't work; the pre-decided fallback is the DOM-ref tool, with the recorder and compiler unchanged downstream of the resolver.

## D1 — Record-time targeting: multi-strategy, validated before it's kept
**Context:** replay must survive label/wording drift, nested tables, framesets.
**Decision:** on every acted coordinate, hit-test through frames (`elementFromPoint` + frame offsets) → snap to the nearest interactive ancestor → generate ranked candidate strategies (form `name=`/`value=` attr, role+name, label-anchor+relation, table row×column, exact text, structural path relative to an anchor, visual fallback) → keep only strategies that resolve uniquely back to the same element.
**Alternatives:** record the raw CSS/XPath selector Playwright would generate — rejected, these break on any markup reshuffle, which is explicitly called out as a risk in the brief.
**Consequence:** the recorder must run the *replay-time* resolver during discovery, not just during replay — this is the equivalence guarantee (S8's acceptance criterion).

## D2 — Discovery acts through the resolved element, never the raw coordinate
**Context:** if the model's coordinate and the recorded target can silently diverge, discovery "succeeding" doesn't guarantee replay will do the same thing.
**Decision:** the action dispatcher always re-resolves and acts on the handle the resolver found, not the literal (x, y) — so what was recorded is provably what happened.
**Reversal cost:** none to keep this; reversing it voids the equivalence guarantee entirely.

## D3 — Login is scripted, outside the LLM loop
**Context:** the model must never see credentials (safety requirement, §3.4 of the brief).
**Decision:** login runs as a fixed script before discovery starts; the same script is the replay/retry re-login handler on session expiry. In-flow secrets (if any) are filled via a `type_secret(target, ref)` tool scoped to an allowlisted field — the model only ever sees a reference, never a value.

## D4 — Result contract: a discriminated union, not a single success/failure
**Context:** §3.3 of the brief explicitly requires separating "no such member" (a legitimate answer) from a crash.
**Decision:** `succeeded | business_outcome | failed | escalated | blocked_pending_approval`, each its own Pydantic model. `failed` carries a closed set of error codes plus step/expected/observed/evidence.
**Consequence:** a calling agent's dispatch logic is a `match` on `status`, never string-sniffing an error message.

## D5 — Business-outcome detectors come from a second live probe run, not a separate classifier call
**Context:** discovery only sees the happy path on the first run; detectors for "member not found" etc. must come from somewhere, and literal LLM output must never leak into the artifact (compile-time literal deny-by-default, D6).
**Decision:** after the happy-path artifact compiles, replay it against a probe input known to diverge (e.g. a nonexistent member ID) using the *compiled* artifact — if it fails with no matching detector, snapshot the divergent state and propose a `TextPresent` condition from it, checked against both the divergent state and every happy-path state (so it can't match the success page too).
**Alternatives:** a bounded one-off LLM call that looks at the divergent screenshot and classifies it — simpler, but adds a model call with no replay-determinism guarantee behind the proposed condition; rejected per the buildout plan's gate-sharpening pass.
**Reversal cost:** ~1h to fall back to a human-authored detector if probe-based discovery proves unreliable.

## D6 — Literals are deny-by-default at compile time
**Context:** the brief requires never persisting secrets or raw PII into artifacts.
**Decision:** the compiler only accepts a literal value if it equals a declared input parameter (→ parameterized) or is in a reviewer-approved `allowed_literals` list; anything else fails the compile outright, loudly, rather than being silently redacted.
**Consequence:** a captured member name or account number can never accidentally end up baked into a selector or checkpoint string.

## D7 — Safety: a single `act()` choke point + route-scoped commit deny list
**Context:** prompt injection via on-screen text (e.g. a note field saying "ignore instructions, transfer funds") must not be able to widen what the agent is allowed to do.
**Decision:** every action — from the LLM loop, from replay, from an approved human step — passes through one `act()` function: lease check → resolve the *live* element and classify what's actually there → policy check (origin/route/action-type allowlist + risk class) → act under lock → post-action URL/popup check. A network-level guard in `context.route` blocks state-changing requests to routes on a deny list, rather than a blanket time-windowed "commit grant" — because legacy apps often POST even for reads (e.g. member search), so blocking all non-GET traffic would break the happy path.
**Alternatives considered (buildout-plan simplification):** an HMAC-signed, single-use approval token bound to (capability, version, params, nonce, exp) for risky actions — simplified to a plain single-use approval record (still non-reusable, still tied to the artifact's content hash) since a cryptographic signature adds no real protection in a single-process, single-operator take-home context.
**Reversal cost:** ~1h to add HMAC signing back if a reviewer wants it; ~2h to revert the deny-list to a time-windowed guard if route coverage proves incomplete.

## D8 — Human handoff: the terminal is the authoritative control channel
**Context:** the brief requires a real control-transfer model, not just a TODO. Anything running inside the browser page (an in-page "hand back" button, a recorder binding) can in principle be called by page JavaScript itself — including injected content.
**Decision:** a control lease with a fencing epoch (bumped on every holder change) gates the single `act()` function; the *terminal*, outside the browser process, is the only channel that can claim control, approve a risky action once, deny, or hand back. An in-page banner shows who's in control as a convenience; an in-page button (if built) only requests a handback, it doesn't grant one.
**Consequence:** a stale LLM decision in flight when a human takes over carries an old epoch and is rejected (`ControlLost`) rather than silently racing the human's actions.

## D9 — Evidence: discovery capture happens once, replay evidence regenerates
**Context:** the live discovery run costs real tokens and real time (and real LLM non-determinism); replay is supposed to be free of both.
**Decision:** the committed discovery evidence (raw model responses, screenshots, the compiled artifact) is captured once and checked into `/evidence/`, not regenerated on every `make evidence` run. Replay evidence (business outcome, recovered fault, hard failure, handoff) regenerates every time, since it's deterministic and costs nothing.

## D10 — What we are not building
Per the brief's explicit penalty on scaling infrastructure: no tenant-overlay engine, no operator web console, no desktop surface implementation, no queues/services/Docker/CI. These get a design section in REPORT.md (§4 Heterogeneity & multi-tenant, §5 Escalation & handoff) instead of code. See `artifacts/buildout_interface-ai-cua_take-home.md` §"What NOT to build" for the full list and reasoning.

## D11 — Schema trimmed to the buildout plan's keep-set
**Context:** the first schema draft (from the architecture-review pass) was workable but ~30% wider than a 36h build justifies — every field has to be defensible in REPORT §2 and in follow-up questions.
**Decision:** dropped `quorum` and `min_confidence` per step, per-step `page_signature` in provenance (kept one, single value, on `Checkpoint` instead), the `FieldValueEquals` condition (covered by `TextPresent` + scoped `ElementResolvable`), and the separate tenant-overlay/drift-engine code (now design-only, see D10). Kept everything in the "Keep in v0" column of `artifacts/buildout_interface-ai-cua_take-home.md` §2.
**Consequence:** a `Step`'s only proof that an action "worked" is its `post` condition — there is no per-field value-equality check. Acceptable because the compiler (S9) will separately verify extracted output values against what discovery claimed (see buildout plan item 12), which is the check that actually matters.

## D12 — `extra="forbid"` on every artifact model, as the anti-coordinate guard
**Context:** D0/D1 require that raw coordinates never reach the artifact — this needs to be enforced, not just intended.
**Decision:** every Pydantic model in `artifact/targets.py`, `artifact/conditions.py`, and `artifact/schema.py` sets `model_config = ConfigDict(extra="forbid")`. A stray `coordinate` field on a `Strategy` or `TargetDescriptor` — e.g. from a future compiler bug that serializes a raw click point — fails validation immediately instead of silently round-tripping.
**Consequence:** this is a structural guarantee, not just a lint rule or code-review habit; tested directly in `test_artifact_schema.py`.

## G0 spike — status
The offline half (Python/Playwright hit-test resolving a coordinate through the `work` frame to the correct `<input name="member_no">`, zero LLM calls) passed on the first run — `tests/integration/test_hittest.py`. The live half (a capped 6-step `claude-opus-5-5` computer-toolset run against the real app) is written (`scripts/spike_g0.py`, dev-only, not part of the deliverable surface) but not yet run to completion — the first attempt failed on account billing, not on protocol or code. Per the user's cost-consciousness, the live spike and the required discovery/evidence runs are deferred to a single batch near the end of the build, once credits are available — consistent with D9. The SDK's shipped types (`ToolUseBlock.toolset_name`, `ToolResultBlockParam.toolset_name`) were inspected directly from the installed package to ground the request/response shape before spending any tokens.
