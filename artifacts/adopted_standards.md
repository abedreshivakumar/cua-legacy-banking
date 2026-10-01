# Engineering standards this project holds itself to

This is the source of truth for `docs/DECISIONS.md`'s standards note. It exists because a standalone system still deserves explicit, checkable conventions rather than ad-hoc style — these were chosen deliberately, not inherited from the project's own code.

## Code style

- Python 3.12+, type hints everywhere.
- `ruff` for formatting and linting — auto-run after every file edit during the build, and as `make lint`.
- `uv` as the package manager.
- Imports: stdlib → third-party → local, alphabetized within groups.
- Files 200–400 lines typical, 800 max. Functions <50 lines. Nesting ≤4 levels — early returns.
- No hardcoded values — constants or config (`.env` / a `Settings` object), not magic numbers inline.
- `structlog` for logging — never `print()`.

## Testing

- RED → GREEN → IMPROVE for the risky pieces: the hit-test/element resolver, the replay classifier, the policy/`act()` gate, the compiler's parameterize/prune rules.
- Target ≥80% coverage on `src/cua/` (not the mock target app or evidence scripts, which are fixtures/tooling, not the system under evaluation).
- Edge-case checklist for every component that touches live input:
  - null / empty / malformed input → Pydantic field validation on every artifact input.
  - invalid / expired auth → session-expiry detector + scripted re-login; secret-ref resolution failures.
  - unreachable / slow dependency → target app down, slow load fault, transient timeout handling.
  - concurrent operations → control-lease epoch races during human handoff (automation acting with a stale epoch).
  - large/adversarial input → a probe input used for business-outcome discovery (e.g. member 999999), oversized memo field, malformed member ID.

## Security checklist

- Every Pydantic artifact field is constrained (`Field(..., min_length=..., pattern=...)`), not just typed.
- No raw exception details ever reach the model's tool_result or get written to logs/evidence.
- No PII in log output — enforced by the fail-closed redaction processor, checked at release time as an explicit checklist item.

## Workflow habits

- Auto-format Python with `ruff` after every edit.
- A commit checkpoint after each meaningful change, aligned with the buildout plan's phase gates (G0–G7): each gate passing is a commit point.

## Git conventions

- Commit format: `type: description` (`feat`, `fix`, `test`, `docs`, `chore`).
- Branch naming: `feat/s<N>-<short-desc>` using this project's local story IDs (S1–S16), e.g. `feat/s7-discovery-loop`.

## Model/effort discipline (how the build itself is worked, not the product)

- Routine implementation stories → standard effort.
- Genuinely hard design calls (schema freeze, the resolver/targeting logic, the compiler's rules, the error-taxonomy priority order, the control-transfer state machine) → higher reasoning effort, written directly rather than generated.
