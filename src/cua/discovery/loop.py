"""The discovery loop: observe -> decide -> act, with no coordinate ever
trusted past the moment it's acted on (docs/DECISIONS.md D0/D1/D2)."""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from playwright.async_api import Page

from cua.artifact.targets import TargetDescriptor
from cua.control.lease import ControlLease
from cua.discovery.actions import execute_action
from cua.discovery.model_client import ModelClient
from cua.discovery.recorder import verify_output_on_page
from cua.discovery.targeting import locate_output_target

MAX_STEPS = 20
# record_output is handled separately — it needs DOM verification, not just logging.
_RECORD_TOOLS = {"declare_input", "assert_checkpoint", "report_outcome"}


@dataclass
class ActionLogEntry:
    step: int
    kind: Literal["member_action", "custom_tool", "thinking"]
    name: str
    input: dict[str, Any]
    resolved: dict[str, Any] | None = None
    target: TargetDescriptor | None = None
    text: str | None = None


@dataclass
class DiscoveryResult:
    status: Literal["completed", "escalated", "dead_end", "max_steps"]
    summary: str
    action_log: list[ActionLogEntry] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))


async def _state_signature(page: Page) -> str:
    parts = [page.url]
    for f in page.frames:
        if f.is_detached():
            continue
        try:
            count = await f.evaluate("document.querySelectorAll('*').length")
        except Exception:  # noqa: BLE001 — a mid-navigation frame is expected, not fatal
            count = -1
        parts.append(f"{f.url}:{count}")
    return "|".join(parts)


def _base_fields(block: Any) -> dict:
    fields: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id}
    toolset_name = getattr(block, "toolset_name", None)
    if toolset_name:
        fields["toolset_name"] = toolset_name
    return fields


def _ok_result(block: Any) -> dict:
    return {**_base_fields(block), "content": "OK"}


def _error_result(block: Any, message: str) -> dict:
    return {**_base_fields(block), "content": message, "is_error": True}


def _screenshot_result(block: Any, screenshot_b64: str | None) -> dict:
    if screenshot_b64:
        content: Any = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64},
            }
        ]
    else:
        content = "OK"
    return {**_base_fields(block), "content": content}


async def run_discovery(
    page: Page,
    client: ModelClient,
    goal: str,
    *,
    max_steps: int = MAX_STEPS,
    control_lease: ControlLease | None = None,
    handoff_timeout_s: float = 600,
) -> DiscoveryResult:
    run_id = str(uuid.uuid4())
    messages: list[dict] = [{"role": "user", "content": [{"type": "text", "text": goal}]}]
    action_log: list[ActionLogEntry] = []
    nudged = False

    def make_result(status: Any, summary: str) -> DiscoveryResult:
        return DiscoveryResult(status, summary, action_log, messages, run_id)

    for step in range(1, max_steps + 1):
        response = await client.next_turn(messages)
        messages.append({"role": "assistant", "content": response.content})

        for block in response.content:
            if getattr(block, "type", None) == "thinking" and getattr(block, "text", ""):
                action_log.append(
                    ActionLogEntry(
                        step=step, kind="thinking", name="thinking", input={}, text=block.text
                    )
                )

        if response.stop_reason == "refusal":
            return make_result("escalated", "model refused")

        tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

        if not tool_use_blocks:
            if nudged:
                return make_result("dead_end", "model stopped calling tools twice in a row")
            nudged = True
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Continue using tools to work toward the goal, or call "
                                "goal_complete / request_human if you are genuinely done."
                            ),
                        }
                    ],
                }
            )
            continue
        nudged = False

        tool_results: list[dict] = []
        batch_signature = await _state_signature(page)
        stale = False

        for block in tool_use_blocks:
            name = block.name
            raw_input = block.input

            if name == "goal_complete":
                tool_results.append(_ok_result(block))
                messages.append({"role": "user", "content": tool_results})
                return make_result("completed", raw_input.get("summary", ""))

            if name == "request_human":
                reason = raw_input.get("reason", "")
                if control_lease is not None:
                    control_lease.hand_to_human(reason)
                    resumed = await control_lease.wait_for_release(timeout_s=handoff_timeout_s)
                    if resumed:
                        # Fold the resume nudge into THIS SAME user turn's
                        # content, alongside the tool_result — not a
                        # second back-to-back user message, which would
                        # violate the API's strict role alternation.
                        tool_results.append(_ok_result(block))
                        tool_results.append(
                            {
                                "type": "text",
                                "text": (
                                    "A human operator took over, made changes, and handed "
                                    "control back. Continue working toward the goal from "
                                    "the current screen."
                                ),
                            }
                        )
                        action_log.append(
                            ActionLogEntry(
                                step=step,
                                kind="custom_tool",
                                name="human_handoff",
                                input={"reason": reason, "resumed": True},
                            )
                        )
                        # The human may have changed the screen — any other
                        # tool calls queued in this same batch are now
                        # against stale state, same as a mid-batch
                        # navigation (see the staleness check below).
                        stale = True
                        continue
                    action_log.append(
                        ActionLogEntry(
                            step=step,
                            kind="custom_tool",
                            name="human_handoff",
                            input={"reason": reason, "resumed": False},
                        )
                    )
                tool_results.append(_ok_result(block))
                messages.append({"role": "user", "content": tool_results})
                return make_result("escalated", reason)

            if name == "record_output":
                claimed = raw_input.get("value", "")
                if not await verify_output_on_page(page, claimed):
                    tool_results.append(
                        _error_result(block, f"value {claimed!r} not found on the current page")
                    )
                    messages.append({"role": "user", "content": tool_results})
                    return make_result(
                        "escalated", f"record_output mismatch: claimed {claimed!r} is not on screen"
                    )
                output_target = await locate_output_target(page, claimed)
                action_log.append(
                    ActionLogEntry(
                        step=step,
                        kind="custom_tool",
                        name=name,
                        input=raw_input,
                        target=output_target,
                    )
                )
                tool_results.append(_ok_result(block))
                continue

            if name in _RECORD_TOOLS:
                action_log.append(
                    ActionLogEntry(step=step, kind="custom_tool", name=name, input=raw_input)
                )
                tool_results.append(_ok_result(block))
                continue

            if stale:
                tool_results.append(_error_result(block, "screen changed; re-observe"))
                continue

            screenshot_b64, resolved, target = await execute_action(page, name, raw_input)
            action_log.append(
                ActionLogEntry(
                    step=step,
                    kind="member_action",
                    name=name,
                    input=raw_input,
                    resolved=resolved,
                    target=target,
                )
            )

            if name not in ("screenshot", "zoom"):
                new_signature = await _state_signature(page)
                if new_signature != batch_signature:
                    stale = True

            tool_results.append(_screenshot_result(block, screenshot_b64))

        messages.append({"role": "user", "content": tool_results})

    return make_result("max_steps", f"stopped after {max_steps} steps")
