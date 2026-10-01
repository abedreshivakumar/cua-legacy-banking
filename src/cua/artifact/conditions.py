"""The condition language: what a step waits on, what a detector matches
against, and what a checkpoint asserts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cua.artifact.targets import ScopeStep, TargetDescriptor


class TextPresent(BaseModel):
    """True if visible text in the given scope matches. `text` and `pattern`
    may contain `{{ inputs.x }}` templates, resolved at replay time."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["text_present"] = "text_present"
    scope: list[ScopeStep] = []
    text: str | None = None
    pattern: str | None = None
    visible_only: bool = True

    @model_validator(mode="after")
    def _one_of_text_or_pattern(self) -> "TextPresent":
        if not self.text and not self.pattern:
            raise ValueError("text_present needs either text or pattern")
        return self


class ElementResolvable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["element_resolvable"] = "element_resolvable"
    target: TargetDescriptor


class LocationMatches(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["location_matches"] = "location_matches"
    route_pattern: str


class OutputsPresent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["outputs_present"] = "outputs_present"
    names: list[str] = Field(min_length=1)


class AllOf(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["all"] = "all"
    conditions: list["Condition"] = Field(min_length=1)


class AnyOf(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["any"] = "any"
    conditions: list["Condition"] = Field(min_length=1)


class NotCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["not"] = "not"
    condition: "Condition"


_ConditionUnion = (
    TextPresent
    | ElementResolvable
    | LocationMatches
    | OutputsPresent
    | AllOf
    | AnyOf
    | NotCondition
)
Condition = Annotated[_ConditionUnion, Field(discriminator="type")]

AllOf.model_rebuild()
AnyOf.model_rebuild()
NotCondition.model_rebuild()
