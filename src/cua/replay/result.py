"""The replay result contract: a discriminated union so a calling agent
can tell a business outcome from a recoverable blip from a hard failure."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FailureCode = Literal[
    "target_unresolved",
    "postcondition_timeout",
    "checkpoint_mismatch",
    "app_error",
    "recovery_exhausted",
    "policy_denied",
    "outcome_unknown",
    "input_invalid",
]


class StepTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    strategy_used: str | None
    duration_ms: int
    # True when resolution fell through to a strategy other than the
    # target's first-ranked one — a soft signal that the surface has
    # drifted from what discovery originally saw, even though the step
    # still succeeded. Never set for a step with only one strategy.
    drifted: bool = False


class RunResultBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    capability: str
    version: str
    effective_sha256: str
    trace: list[StepTrace] = []
    recoveries: list[str] = []  # detector ids that fired and were recovered from, in order
    side_effects_committed: Literal["none", "possible", "yes"] = "none"


class Succeeded(RunResultBase):
    status: Literal["succeeded"] = "succeeded"
    outputs: dict[str, Any]


class BusinessOutcomeResult(RunResultBase):
    status: Literal["business_outcome"] = "business_outcome"
    outcome: str
    details: dict[str, str] = {}


class Failed(RunResultBase):
    status: Literal["failed"] = "failed"
    code: FailureCode
    step_id: str
    expected: str
    observed: str
    retryable: bool = False


class Escalated(RunResultBase):
    status: Literal["escalated"] = "escalated"
    reason: str
    step_id: str


class BlockedPendingApproval(RunResultBase):
    status: Literal["blocked_pending_approval"] = "blocked_pending_approval"
    reason: str
    step_id: str | None = None


RunResult = Annotated[
    Succeeded | BusinessOutcomeResult | Failed | Escalated | BlockedPendingApproval,
    Field(discriminator="status"),
]
