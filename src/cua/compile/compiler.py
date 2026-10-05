"""Compile a completed discovery run into a reviewable, draft Capability.

Literals are deny-by-default (D6): every typed value must have a matching
declare_input call, or the compile fails outright rather than silently
baking a literal into the artifact.
"""

import hashlib
import re
from datetime import UTC, datetime
from typing import Literal

from cua.artifact.conditions import AllOf, Condition, ElementResolvable, OutputsPresent
from cua.artifact.schema import (
    AppBinding,
    Capability,
    Checkpoint,
    DeclaredOutcome,
    Entry,
    Extraction,
    InputParam,
    OutputField,
    PostCondition,
    Provenance,
    Risk,
    Step,
)
from cua.discovery.loop import ActionLogEntry, DiscoveryResult

COMPILER_VERSION = "0.1.0"

_CLICKABLE_MEMBER_ACTIONS = {"left_click", "double_click", "right_click"}
_COMMIT_VOCAB = re.compile(
    r"(?i)\b(submit|transfer|delete|confirm|post|save|pay|close|approve|disburse|reverse|void)\b"
)
_MONEY_SHAPED = re.compile(r"^\$?\s*\d[\d,]*\.\d{2}$")


class CompileError(Exception):
    """A discovery run can't be compiled as-is — see the message for which
    step and why. Never silently drops information to make it pass."""


def _classify_risk(entry: ActionLogEntry) -> Risk:
    if entry.name == "type" or entry.name == "type_secret":
        return "input"
    if entry.name in _CLICKABLE_MEMBER_ACTIONS:
        text = (entry.resolved or {}).get("text", "") or ""
        return "commit_irreversible" if _COMMIT_VOCAB.search(text) else "query"
    return "observe"


def _synthesize_summary(
    capability_id: str,
    inputs: list[InputParam],
    outputs: list[OutputField],
    outcomes: list[DeclaredOutcome],
) -> str:
    """Generic, by structure only — never the model's own completion text,
    which (like `goal_complete`'s summary) typically names the literal
    input value discovery happened to use. Same deny-by-default spirit as
    D6, extended to this field: found by the G3-style check actually
    grepping a compiled artifact for the discovery input, not by review."""
    parts = [f"Capability {capability_id!r}."]
    if inputs:
        parts.append("Inputs: " + ", ".join(i.name for i in inputs) + ".")
    if outputs:
        parts.append("Outputs: " + ", ".join(o.name for o in outputs) + ".")
    if outcomes:
        parts.append("Outcomes: " + ", ".join(o.name for o in outcomes) + ".")
    return " ".join(parts)


def _transcript_sha256(result: DiscoveryResult) -> str:
    parts = []
    for e in result.action_log:
        target_json = e.target.model_dump_json() if e.target else ""
        parts.append(f"{e.step}|{e.kind}|{e.name}|{e.input}|{target_json}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def compile_capability(
    result: DiscoveryResult,
    *,
    capability_id: str,
    version: str,
    entry_route: str,
    login_script_ref: str,
    app: AppBinding,
    model: str,
) -> Capability:
    if result.status != "completed":
        raise CompileError(
            f"cannot compile a {result.status!r} run — only 'completed' runs compile"
        )

    declared_inputs: dict[str, str] = {}  # typed literal -> param name
    inputs: list[InputParam] = []
    outputs: list[OutputField] = []
    outcomes: list[DeclaredOutcome] = []

    for e in result.action_log:
        if e.kind != "custom_tool":
            continue
        if e.name == "declare_input":
            name, value = e.input["name"], e.input["value"]
            declared_inputs[value] = name
            inputs.append(
                InputParam(
                    name=name,
                    type="string",
                    sensitivity="pii",
                    description=e.input.get("rationale", ""),
                )
            )
        elif e.name == "report_outcome":
            outcomes.append(
                DeclaredOutcome(name=e.input["name"], description=e.input.get("rationale", ""))
            )

    # Steps: every clickable/typeable member_action, in order. Built in two
    # passes — each step's post-condition depends on the NEXT step's target
    # (or, for the last step, on the outputs), so Step objects aren't
    # constructed until every target in the sequence is known.
    step_specs: list[dict] = []
    last_click_target = None  # `type` has no target of its own — it types
    # into whatever the preceding click focused, so that's its target too.
    for e in result.action_log:
        if e.kind != "member_action" or e.name not in (
            _CLICKABLE_MEMBER_ACTIONS | {"type", "type_secret"}
        ):
            continue

        if e.name in _CLICKABLE_MEMBER_ACTIONS:
            if e.target is None:
                raise CompileError(
                    f"step {len(step_specs) + 1} ({e.name}) has no resolved target — "
                    "discovery fell back to a raw coordinate; cannot compile"
                )
            last_click_target = e.target
            target = e.target
        else:
            if last_click_target is None:
                raise CompileError(
                    f"step {len(step_specs) + 1} ({e.name}) has no preceding click to "
                    "inherit a target from — cannot compile"
                )
            target = last_click_target

        value = None
        if e.name == "type":
            typed = e.input.get("text", "")
            if typed not in declared_inputs:
                raise CompileError(
                    f"literal {typed!r} typed in step {len(step_specs) + 1} has no matching "
                    "declare_input — literals are deny-by-default (see docs/DECISIONS.md D6)"
                )
            value = "{{ inputs." + declared_inputs[typed] + " }}"

        risk = _classify_risk(e)
        step_specs.append(
            {
                "id": f"step_{len(step_specs) + 1}_{e.name}",
                "intent": f"{e.name} (discovered, step {e.step})",
                "action": "type" if e.name == "type" else "click",
                "target": target,
                "value": value,
                "risk": risk,
                "idempotent": risk != "commit_irreversible",
            }
        )

    if not step_specs:
        raise CompileError("no clickable/typeable steps in this run — nothing to compile")

    # Outputs: every record_output with a located target. If the claimed
    # value is money-shaped, infer the transforms that will be needed to
    # match it — the DOM text usually carries a "$" / thousands-comma the
    # model's claimed value doesn't, which `strip` alone can't fix.
    for e in result.action_log:
        if e.kind != "custom_tool" or e.name != "record_output":
            continue
        if e.target is None:
            raise CompileError(
                f"output {e.input['name']!r} has no located extraction target — cannot compile"
            )
        claimed = e.input.get("value", "")
        if _MONEY_SHAPED.match(claimed):
            output_type: Literal["string", "int", "decimal", "date", "bool"] = "decimal"
            transforms = ["strip", "remove_dollar_sign", "remove_commas", "to_decimal"]
        else:
            output_type = "string"
            transforms = ["strip"]
        outputs.append(
            OutputField(
                name=e.input["name"],
                type=output_type,
                sensitivity="pii",
                required=True,
                extract=Extraction(target=e.target, read="text", transforms=transforms),
            )
        )

    # Post-conditions: each step waits for the next step's target to be
    # resolvable. The last step waits for every output's OWN extraction
    # target to be resolvable — NOT OutputsPresent, which can never become
    # true here: the replay engine only extracts outputs after every step's
    # post-condition has already passed (see replay/engine.py). Checking
    # OutputsPresent this early is a dead end that times out every time —
    # found by actually replaying a compiled artifact, not by inspection.
    steps: list[Step] = []
    for i, spec in enumerate(step_specs):
        when: Condition
        if i + 1 < len(step_specs):
            when = ElementResolvable(target=step_specs[i + 1]["target"])
        elif outputs:
            output_targets: list[Condition] = [
                ElementResolvable(target=o.extract.target) for o in outputs
            ]
            when = (
                output_targets[0] if len(output_targets) == 1 else AllOf(conditions=output_targets)
            )
        else:
            when = ElementResolvable(target=spec["target"])
        steps.append(Step(**spec, post=PostCondition(when=when, timeout_ms=10000)))

    risk_order = [
        "observe",
        "navigate",
        "input",
        "query",
        "commit_reversible",
        "commit_irreversible",
    ]
    max_risk = max((s.risk for s in steps), key=risk_order.index)
    side_effects: Literal["read_only", "reversible_write", "irreversible_write"]
    if max_risk == "commit_irreversible":
        side_effects = "irreversible_write"
    elif max_risk == "commit_reversible":
        side_effects = "reversible_write"
    else:
        side_effects = "read_only"

    first_target, last_target = steps[0].target, steps[-1].target
    assert first_target is not None and last_target is not None  # guaranteed by step_specs above

    checkpoint_when: Condition = (
        OutputsPresent(names=[o.name for o in outputs])
        if outputs
        else ElementResolvable(target=last_target)
    )

    return Capability(
        id=capability_id,
        version=version,
        status="draft",
        summary=_synthesize_summary(capability_id, inputs, outputs, outcomes),
        app=app,
        side_effects=side_effects,
        inputs=inputs,
        outputs=outputs,
        outcomes=outcomes,
        entry=Entry(
            route=entry_route,
            login_script_ref=login_script_ref,
            condition=ElementResolvable(target=first_target),
        ),
        steps=steps,
        detectors=[],  # detector synthesis is a probe-run exercise, not this compiler's job (S11)
        checkpoint=Checkpoint(when=checkpoint_when),
        provenance=Provenance(
            discovery_run_id=result.run_id,
            model=model,
            recorded_at=datetime.now(UTC),
            transcript_sha256=_transcript_sha256(result),
            compiler_version=COMPILER_VERSION,
        ),
    )
