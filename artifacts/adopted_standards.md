# Adopted coding standards (from DartIQ's cross-repo rules, value-adds only)

This project is standalone — not DartIQ — so DartIQ's backend/API-specific conventions (ApiResponse envelope, RequireMSPUser/TenantDB, Mongo/Motor, FastAPI route-per-resource, Jira-scoped git workflow, DartIQ agent-orchestration rules) do **not** apply here. What follows is only the subset of DartIQ's standards that is generically useful and was deliberately pulled in. This file is the source of truth for `docs/DECISIONS.md` once S1 (scaffold) creates it.

## Code style (from `coding-style.md`, cross-repo section only)
- Python 3.12+, type hints everywhere.
- `ruff` for formatting and linting — wired as a pre-commit / `make lint` step, and auto-run after every file edit during the build.
- `uv` as the package manager (already the plan's choice).
- Imports: stdlib → third-party → local, alphabetized within groups.
- Files 200–400 lines typical, 800 max. Functions <50 lines. Nesting ≤4 levels — early returns.
- No hardcoded values — constants or config (`.env` / a `Settings` object), not magic numbers inline.
- `structlog` for logging — never `print()` (already in the plan as the base of the redaction pipeline).

## Testing (from `testing.md`, principles only)
- RED → GREEN → IMPROVE for the risky pieces: the hit-test/element resolver, the replay classifier, the policy/`act()` gate, the compiler's parameterize/prune rules.
- Target ≥80% coverage on `src/cua/` (not the mock target app or evidence scripts, which are fixtures/tooling, not the system under evaluation).
- Edge-case checklist, reworded for this system instead of DartIQ's examples:
  - null / empty / malformed input → Pydantic field validation on every artifact input.
  - invalid / expired auth → session-expiry detector + scripted re-login; secret-ref resolution failures.
  - unreachable / slow dependency → target app down, slow load fault, transient timeout handling.
  - concurrent operations → control-lease epoch races during human handoff (automation acting with a stale epoch).
  - large/adversarial input → a probe input used for business-outcome discovery (e.g. member 999999), oversized memo field, malformed member ID.

## Security checklist (from `security.md`, principles only)
- Every Pydantic artifact field is constrained (`Field(..., min_length=..., pattern=...)`), not just typed — mirrors DartIQ's "input validated via Pydantic models with field constraints."
- No raw exception details ever reach the model's tool_result or get written to logs/evidence — reworded from DartIQ's "no raw exception details" API rule.
- No PII in log output — enforced by the fail-closed redaction processor (already in the plan), checked at release time as an explicit checklist item, same spirit as DartIQ's "no PII in log output (structlog configured with sanitizers)."

## Workflow habits (from `hooks.md`)
- Auto-format Python with `ruff` after every edit.
- TodoWrite tracks the milestone/story list (S1–S16) rather than living only in conversation.
- A commit checkpoint after each meaningful change — naturally aligned with the buildout plan's phase gates (G0–G7): each gate passing is a commit point.

## Git conventions (from `git-workflow.md`, adapted — no DartIQ repo scopes or Jira keys)
- Commit format: `type: description` (`feat`, `fix`, `test`, `docs`, `chore`) — no `(scope)` since there's one repo here.
- Branch naming: `feat/s<N>-<short-desc>` using this project's local story IDs (S1–S16) in place of DartIQ ticket keys, e.g. `feat/s7-discovery-loop`.

## Model/effort discipline (from `performance.md`, applied to *how I work*, not the product)
- Routine implementation stories → standard effort.
- Genuinely hard design calls (schema freeze, the resolver/targeting logic, the compiler's rules, the error-taxonomy priority order, the control-transfer state machine) → higher reasoning effort, and per the buildout plan (§8) these stay off the agent-delegation list — written directly, not generated.

## Explicitly NOT adopted (DartIQ-specific, doesn't fit a standalone system)
- `ApiResponse` envelope, `RequireMSPUser`/`TenantDB` dependencies, Mongo/Motor, FastAPI route-per-resource conventions.
- Jira ticket keys, DartIQ repo-scoped commit prefixes, DartIQ agent-orchestration routing rules.
- `patterns.md`'s FastAPI/Pydantic examples beyond the generic "validate → execute → respond" shape, which already matches our CLI/replay command structure.
