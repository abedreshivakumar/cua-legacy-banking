"""The capability artifact: a typed, versioned, reviewable contract that an
AI agent can invoke, and that replay can run without a model in the loop."""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cua.artifact.conditions import Condition
from cua.artifact.targets import TargetDescriptor

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

Sensitivity = Literal["public", "internal", "pii", "secret"]
Risk = Literal["observe", "navigate", "input", "query", "commit_reversible", "commit_irreversible"]


class AppBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor: str
    product: str
    version_range: str
    surface: Literal["web"] = "web"


class InputParam(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: Literal["string", "int", "decimal", "date", "enum", "secret_ref"]
    pattern: str | None = None
    min_len: int | None = None
    max_len: int | None = None
    enum: list[str] | None = None
    sensitivity: Sensitivity
    description: str


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: TargetDescriptor
    read: Literal["text", "value", "attr"]
    attr_name: str | None = None
    transforms: list[str] = []


class OutputField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: Literal["string", "int", "decimal", "date", "bool"]
    sensitivity: Literal["public", "internal", "pii"]
    extract: Extraction
    required: bool = True


class DeclaredOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: str
    login_script_ref: str | None = None
    condition: Condition


class PostCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    when: Condition
    timeout_ms: int = 5000


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    intent: str
    action: Literal["navigate", "click", "type", "type_secret", "select", "press", "extract"]
    target: TargetDescriptor | None = None
    value: str | None = None  # a "{{ inputs.x }}" template, a $labels ref, or a literal
    risk: Risk
    pre: Condition | None = None
    post: PostCondition
    idempotent: bool = True


class DismissHandler(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["dismiss"] = "dismiss"
    target: TargetDescriptor
    then: Literal["resume_step", "retry_step", "restart_entry"] = "resume_step"


class ReloginHandler(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["relogin"] = "relogin"
    script_ref: str
    then: Literal["resume_step", "retry_step", "restart_entry"] = "retry_step"


class BackoffHandler(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["backoff"] = "backoff"
    wait_ms: int = 1000
    then: Literal["resume_step", "retry_step"] = "retry_step"


Handler = Annotated[DismissHandler | ReloginHandler | BackoffHandler, Field(discriminator="type")]


class Detector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["recoverable", "hard_failure", "escalate", "business_outcome"]
    when: Condition
    active: Literal["always"] | list[str] = "always"
    priority: int = 0
    outcome: str | None = None  # required when kind == "business_outcome"
    handler: Handler | None = None  # required when kind == "recoverable"
    max_attempts: int = 1
    origin: Literal["library", "discovered", "human"] = "library"


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    when: Condition
    page_signature: str | None = None


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    discovery_run_id: str
    model: str
    recorded_at: datetime
    transcript_sha256: str
    compiler_version: str


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approver: str | None = None
    approved_at: datetime | None = None
    content_sha256: str | None = None


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    id: str
    version: str
    status: Literal["draft", "approved"] = "draft"
    summary: str
    app: AppBinding
    side_effects: Literal["read_only", "reversible_write", "irreversible_write"]
    labels: dict[str, str] = {}
    allowed_literals: list[str] = []
    inputs: list[InputParam] = []
    outputs: list[OutputField] = []
    outcomes: list[DeclaredOutcome] = []
    entry: Entry
    steps: list[Step] = Field(min_length=1)
    detectors: list[Detector] = []
    checkpoint: Checkpoint
    provenance: Provenance
    review: Review | None = None

    @field_validator("version")
    @classmethod
    def _version_is_semver(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            raise ValueError(f"version must be semver (X.Y.Z), got {v!r}")
        return v
