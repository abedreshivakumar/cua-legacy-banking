"""Build a checked TargetDescriptor from a hit-test's facts — shared by
the live action dispatcher (resolve before act, D2) and the recorder."""

from typing import Any

from playwright.async_api import Page

from cua.artifact.targets import (
    AttrStrategy,
    ElementExpectation,
    ElementKind,
    ScopeStep,
    Strategy,
    TableCellStrategy,
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


_LOCATE_TABLE_VALUE_JS = """
(valueText) => {
  for (const table of document.querySelectorAll('table')) {
    const rows = Array.from(table.rows);
    if (rows.length < 2) continue;
    const headerCells = Array.from(rows[0].cells);
    for (const row of rows.slice(1)) {
      const cells = Array.from(row.cells);
      for (let colIdx = 0; colIdx < cells.length; colIdx++) {
        if (cells[colIdx].textContent.trim().includes(valueText.trim())) {
          const rowAnchor = cells[0].textContent.trim();
          const columnHeader = headerCells[colIdx] ? headerCells[colIdx].textContent.trim() : null;
          if (columnHeader && rowAnchor) return [rowAnchor, columnHeader];
        }
      }
    }
  }
  return null;
}
"""


async def locate_output_target(page: Page, value: str) -> TargetDescriptor | None:
    """Find where a claimed output value lives right now, as a table_cell
    target — the only extraction shape v0 supports. A value that isn't in
    a table (plain text, a list) isn't located; the compiler then flags
    that output for manual review instead of guessing a target."""
    for frame in page.frames:
        if frame.is_detached():
            continue
        try:
            result = await frame.evaluate(_LOCATE_TABLE_VALUE_JS, value)
        except Exception:  # noqa: BLE001 — a mid-navigation frame isn't fatal here
            continue
        if result:
            row_anchor, column_header = result
            scope = [ScopeStep(name=frame.name)] if frame.name else []
            return TargetDescriptor(
                scope=scope,
                expect=ElementExpectation(kind="cell"),
                strategies=[TableCellStrategy(row_anchor=row_anchor, column_header=column_header)],
            )
    return None
