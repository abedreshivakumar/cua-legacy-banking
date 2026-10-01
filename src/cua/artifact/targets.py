"""Element target descriptors: how a step finds its control, as several
ranked, independently-checkable strategies — never a raw coordinate."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ScopeStep(BaseModel):
    """One level of frame nesting to descend into before resolving."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["frame"] = "frame"
    name: str | None = None
    src_pattern: str | None = None
    index: int | None = None


class ElementExpectation(BaseModel):
    """A guard against resolving onto the wrong element after drift."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["textbox", "button", "link", "cell", "select", "generic"] = "generic"
    editable: bool | None = None
    forbidden_text_pattern: str | None = None  # e.g. r"(?i)\b(void|delete)\b"


class AttrStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: Literal["attr"] = "attr"
    attr: str
    value: str


class RoleStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: Literal["role"] = "role"
    role: str
    name: str


class AnchorStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: Literal["anchor"] = "anchor"
    text: str  # may be a "$labels.key" reference
    relation: Literal["same_row", "right_of", "below", "in_cell_after"]
    control: str
    nth: int = 0


class TableCellStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: Literal["table_cell"] = "table_cell"
    row_anchor: str
    column_header: str


class TextStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: Literal["text"] = "text"
    text: str
    match: Literal["exact", "contains"] = "exact"


class StructuralStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: Literal["structural"] = "structural"
    path: str  # relative to an anchor, never from the document root


class VisualStrategy(BaseModel):
    """Last-resort fallback when no structural strategy resolves uniquely."""

    model_config = ConfigDict(extra="forbid")
    by: Literal["visual"] = "visual"
    anchor_text: str
    offset_x: int
    offset_y: int


_StrategyUnion = (
    AttrStrategy
    | RoleStrategy
    | AnchorStrategy
    | TableCellStrategy
    | TextStrategy
    | StructuralStrategy
    | VisualStrategy
)
Strategy = Annotated[_StrategyUnion, Field(discriminator="by")]


class TargetDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: list[ScopeStep] = []
    expect: ElementExpectation = ElementExpectation()
    strategies: list[Strategy] = Field(min_length=1)
    resolved_from: Literal["coordinate", "human", "edited"] = "coordinate"
