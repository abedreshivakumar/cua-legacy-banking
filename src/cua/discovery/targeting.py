"""Build a checked TargetDescriptor from a hit-test's facts — shared by
the live action dispatcher (resolve before act, D2) and the recorder."""

from typing import Any

from cua.artifact.targets import (
    AttrStrategy,
    ElementExpectation,
    ElementKind,
    ScopeStep,
    Strategy,
    TargetDescriptor,
    TextStrategy,
)

_KIND_BY_TAG: dict[str, ElementKind] = {
    "A": "link",
    "BUTTON": "button",
    "SELECT": "select",
    "TD": "cell",
    "TH": "cell",
}


def _infer_kind(facts: dict[str, Any]) -> ElementKind:
    tag = (facts.get("tag") or "").upper()
    if tag == "INPUT":
        input_type = (facts.get("type") or "").lower()
        return "button" if input_type in ("submit", "image") else "textbox"
    return _KIND_BY_TAG.get(tag, "generic")


def target_from_facts(facts: dict[str, Any]) -> TargetDescriptor | None:
    strategies: list[Strategy] = []
    name = facts.get("name")
    if name:
        strategies.append(AttrStrategy(attr="name", value=name))
    text = (facts.get("text") or "").strip()
    if text:
        strategies.append(TextStrategy(text=text, match="exact"))
    if not strategies:
        return None

    scope = [ScopeStep(name=n) for n in (facts.get("framePath") or []) if n]
    return TargetDescriptor(
        scope=scope,
        expect=ElementExpectation(kind=_infer_kind(facts)),
        strategies=strategies,
    )
