# Assignment brief — interface.ai Take-Home: Computer-Use Automation System

Transcribed from "Assignment A — Computer-Use Automation System.pdf". This is the source of truth for scope.

**Format:** Design + working implementation + short write-up. Public GitHub repo (the candidate publishes it themselves).
**Time box:** No deadline; focused effort, not a polished product.
**Evaluated:** how you design and implement a computer-use system under realistic constraints. Clear thinking, sound trade-offs, and a working core over breadth.

## 1. Context

interface.ai builds AI agents for banks and credit unions. This project is the backend integration layer that gives those agents hands — the system that lets an AI agent operate an institution's back-office applications.

APIs are always preferred and out of scope. This system exists for the long tail of legacy applications with no API at all (core banking screens, servicing tools, admin consoles) where the only way in is to drive the UI like a human operator. It uses an LLM ("computer use") to figure out how to accomplish a task the first time, then turns what it learned into deterministic, replayable automation that no longer needs the model in the loop. Each recording becomes a reusable, reviewable, parameterized capability that AI agents invoke on demand — reliably and cheaply — without re-reasoning about the UI every time.

The agent-facing product decides *what* to do; this system is how it reliably and safely does it inside legacy bank software.

### The real environment
- **Stable UIs, but real runtime errors.** UIs change slowly (record-once / replay-many is viable). The hard part: replay must accommodate errors and exceptional states that legitimately occur at runtime — validation errors, "record not found", permission denials, unexpected confirmation dialogs, session/timeout expiry, transient slowness, outright app errors. Happy-path-only is not useful.
- **Heterogeneous, often legacy surfaces.** Modern web, legacy web (server-rendered, framesets, deeply nested tables, non-semantic markup, no test IDs), or native desktop. Cannot assume clean DOM, stable selectors, or an API. Often the only reliable surface is what a human operator sees and does.
- **Multi-tenant at scale.** Hundreds of tenants, each ~20 apps — thousands of app instances. Many tenants run the same vendor product configured, branded, versioned differently. Automation for one tenant should ideally generalize — or degrade gracefully — across others rather than be rebuilt.

Intentionally under-specified: where the brief doesn't dictate, make a decision and say why.

## 2. The problem — build a system that can
1. Take a goal in natural language for a target application (e.g. "look up member 12345 and read their current savings balance", "open a new sub-account for this member and reach the confirmation screen").
2. Use an LLM to accomplish it by driving a real application surface — observe, decide, act. Browser is one case of general computer use (a11y tree, screenshot + coordinates, OS automation are fair game).
3. Record the successful run as a structured, reusable artifact — typed, versioned description of the flow (steps, how each target element is identified, data to extract), decoupled from the raw model transcript.
4. Replay that artifact deterministically — without the LLM in the decision loop, using stable targeting, reporting success/failure.
5. Escalate to a human when stuck — route an intervention request to a human operator, let them take control of the live session, then hand control back.
6. Stay within safety guardrails — allowlist of permitted actions; avoid leaking or persisting sensitive data (regulated financial data).

Through-line: **The model discovers. The artifact becomes a reusable capability. Deterministic replay is how the AI agent invokes it in production.**

## 3. Core requirements (must-have)

### 3.1 Goal-driven agent loop
- Accept goal + target (app/URL/entry point).
- LLM observe → decide → act loop against a live surface until goal met or stop condition (max steps, timeout, dead-end).
- Must interact with a real UI (click, type, navigate, read state). Bias toward an approach that still works with no clean DOM.

### 3.2 Structured artifact (an agent-invocable capability)
Typed, serializable artifact — a capability an AI agent can call, with a clear contract. At minimum:
- ordered steps / actions
- how each target element/control is identified (with reasoning about robustness)
- typed input parameters (supplied per invocation, e.g. member ID)
- typed outputs / data to extract and their shape
- a checkpoint or success condition
Versioned and reviewable — human reviewer and calling agent can understand what it does, needs, returns. Schema is a focal point of evaluation.

### 3.3 Deterministic replay (the production execution path)
- Given artifact + input params, replay without invoking the LLM for decisions.
- Stable targeting, verify checkpoint/success condition, return declared outputs.
- Handle errors and exceptional states explicitly (validation error, record not found, permission denial, unexpected dialog, session timeout, slow/failed load). Detect and respond deliberately. Result contract must distinguish:
  - **expected business outcomes** (e.g. "no such member" is legitimate, not a crash),
  - **recoverable conditions** (dismiss known interstitial, wait/retry transient load),
  - **hard failures** (stop, clear debuggable error).
- Structured result: success (with outputs), known business outcome, or failure with debug detail (what step, expected, observed).

### 3.4 Safety & policy guardrails
- Explicit, configurable allowlist (permitted domains/routes, allowed action types). Agent must not act outside it.
- Distinguish safe/reversible vs risky/irreversible actions; handle risky conservatively (block, require confirmation, or flag — justify).
- Never persist secrets or raw sensitive data (credentials, tokens, full PII) into artifacts or logs. Redact.

### 3.5 Evidence / observability
Structured log of what the agent did and why, plus at least one richer signal on failure (screenshot, DOM snapshot, trace).

### 3.6 Human-in-the-loop escalation & handoff
- Detect and route: identify stuck/blocked state; raise intervention request with context (capability/goal, current step, current state or screenshot, why it stopped).
- Take control of the live session: human operates the SAME live session (not a fresh one), performs manual steps, hands control back; run resumes or completes. Preserve context/evidence across handoff; record what the human did.
- Seam: automation can pause, cede control, resume on the same session; there's a way to know who is (or should be) in control.
- Scope: full co-browsing console out of scope. Minimal but real handoff (pause, expose live session for manual control — bare/mock operator surface OK — signal resume, capture human actions) plus a clear design for the rest. Handoff mechanism and control-transfer model must be real.

### 3.7 Design for heterogeneity & scale (design, not necessarily build)
- Surface abstraction: how artifact schema + replay engine extend from the chosen surface to legacy web and/or desktop. The seam between "how we perceive/act on a surface" and "the recorded flow".
- Multi-tenant reuse: represent an artifact so it is reused (or safely specialized/overridden) across tenants running the same app; detect and manage per-tenant/version drift.
Not expected to implement multi-tenant or desktop; core abstractions must not paint into a corner.

## 4. Explicitly the candidate's call
Language/runtime/frameworks; LLM provider/model and prompting/loop structure; computer-use technology; target application (a stand-in — no real bank systems; public demo/sandbox, local sample app, or intentionally hostile surface: iframes/framesets, table layouts, no test IDs; respect ToS, no real credentials/PII); artifact schema and storage; how determinism is achieved; architecture and boundaries (simpler is fine if justified).

**Not the candidate's call: the discovery run must be real.** At least one genuine LLM-driven run against a live surface, evidence in `/evidence/`. Everywhere else a clean seam is fine (operator console, desktop surface) — mock deliberately and document.

## 5. Scope & expectations
AI-assisted development assumed. Wanted: a complete end-to-end vertical slice touching every core requirement:
goal → LLM-driven run that completes it → saved capability artifact → deterministic replay with input params, outputs, error/outcome handling → human-escalation path that takes over the live session → evidence for both runs.
Focus: quality of artifact schema, locator/control-robustness strategy, error taxonomy, control-transfer model, coherence. Go deep on artifact schema, deterministic replay + error handling, safety/escalation model. Cut depth, not whole capabilities. Say what you cut and why, and what you'd build next.

## 6. Deliverables (exact paths and headings)
1. Source code, public repo, `/README.md`: setup and run (keys/config, how to run without live services), demo path (exact commands to run the agent on a goal, then replay the resulting artifact).
2. `/REPORT.md` (~1–3 pages), headings exactly: 1. Architecture · 2. Artifact schema · 3. Determinism & error handling · 4. Heterogeneity & multi-tenant · 5. Escalation & handoff · 6. Safety · 7. Cuts.
3. `/evidence/`: saved example artifact plus logs from a discovery run and a replay run. Ideally one replay hitting an error/exceptional state (bad input, not-found, injected failure). Short screen recording optional.

## 7. Evaluation criteria (roughly in order)
System design (artifact schema + replay contract central) · Correctness of core loop · Robustness & error handling · Human-in-the-loop escalation · Generalization to the real environment · Safety & data handling · Code quality (readable, typed, tested where it counts, easy to run) · Communication.
Not rewarded: feature breadth, framework name-dropping, building scaling infrastructure (queues, clusters, multi-tenant plumbing). A small, correct, well-argued system is the goal.

## 8. Optional stretch goals (at most one or two)
Agent-facing capability catalog/tool interface · code generation from artifact · confidence & draft→approved gating · bounded single-step LLM assisted fallback on replay failure · canonicalization / cross-tenant reuse (base app vs variant with overrides) · multi-run stability.

## 9. Ground rules
AI assistance encouraged; candidate must explain and defend every part. No sites where automation violates ToS or needs real credentials. Keep secrets out of the repo. Self time-box; document next steps if stopping early.
