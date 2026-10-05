"""Resolve a TargetDescriptor to a live element, trying strategies in rank
order. A strategy that matches more than one element is never chosen —
ambiguity falls through to the next strategy, not to a first-match guess.
"""

import re
from dataclasses import dataclass, field

from playwright.async_api import ElementHandle, Frame, Page

from cua.artifact.targets import (
    AnchorStrategy,
    ElementExpectation,
    ScopeStep,
    TableCellStrategy,
    TargetDescriptor,
    TextStrategy,
)

_CONTROL_SELECTORS = {
    "textbox": "input:not([type]), input[type='text'], input[type='password'], textarea",
    "button": "a, button, input[type='submit'], input[type='image']",
    "link": "a",
    "select": "select",
    "cell": "td, th",
}

_ANCHOR_JS = """
([labelText, relation, controlSelector, nth]) => {
  function findLabelElements(root) {
    const all = root.querySelectorAll('td,th,label,span,div,a,font');
    const matches = [];
    for (const el of all) {
      if (el.children.length === 0 && el.textContent.trim() === labelText.trim()) {
        matches.push(el);
      }
    }
    return matches;
  }
  const labelEls = findLabelElements(document);
  if (labelEls.length === 0) return null;
  const labelEl = labelEls[0];

  function controlsWithin(container) {
    if (!container) return [];
    return Array.from(container.querySelectorAll(controlSelector));
  }

  let candidates = [];
  if (relation === 'same_row') {
    candidates = controlsWithin(labelEl.closest('tr'));
  } else if (relation === 'right_of') {
    const td = labelEl.closest('td,th');
    const nextTd = td ? td.nextElementSibling : null;
    candidates = nextTd && nextTd.matches(controlSelector) ? [nextTd] : controlsWithin(nextTd);
  } else if (relation === 'below') {
    const td = labelEl.closest('td,th');
    const tr = labelEl.closest('tr');
    if (td && tr) {
      const idx = Array.prototype.indexOf.call(tr.children, td);
      const nextTr = tr.nextElementSibling;
      const targetTd = nextTr ? nextTr.children[idx] : null;
      candidates = targetTd && targetTd.matches(controlSelector)
        ? [targetTd] : controlsWithin(targetTd);
    }
  } else if (relation === 'in_cell_after') {
    candidates = controlsWithin(labelEl.closest('td,th') || labelEl);
  }
  return candidates[nth] || null;
}
"""

_TABLE_CELL_JS = """
([rowAnchorText, columnHeaderText]) => {
  for (const table of document.querySelectorAll('table')) {
    const rows = Array.from(table.rows);
    if (rows.length === 0) continue;
    const headerCells = Array.from(rows[0].cells);
    const colIdx = headerCells.findIndex(c => c.textContent.trim() === columnHeaderText.trim());
    if (colIdx === -1) continue;
    for (const row of rows.slice(1)) {  // skip the header row itself
      const cells = Array.from(row.cells);
      if (cells.length > 0 && cells[0].textContent.trim() === rowAnchorText.trim()) {
        return cells[colIdx] || null;
      }
    }
  }
  return null;
}
"""


@dataclass
class StrategyAttempt:
    strategy: str
    matched: int
    chosen: bool
    error: str | None = None


@dataclass
class Resolution:
    handle: ElementHandle | None
    strategy_used: str | None
    confidence: float
    attempts: list[StrategyAttempt] = field(default_factory=list)


def _sub_labels(text: str, labels: dict[str, str]) -> str:
    return re.sub(r"\$labels\.(\w+)", lambda m: labels.get(m.group(1), m.group(0)), text)


def frame_for_scope(page: Page, scope: list[ScopeStep]) -> Frame | None:
    frame = page.main_frame
    for step in scope:
        # child_frames can briefly retain detached frames from a previous
        # navigation of the same name — exclude them, or a reload can pick
        # a dead frame and every action on it raises "Frame was detached".
        candidates = [f for f in frame.child_frames if not f.is_detached()]
        next_frame = None
        if step.name:
            next_frame = next((f for f in candidates if f.name == step.name), None)
        elif step.src_pattern:
            pattern = re.compile(step.src_pattern)
            next_frame = next((f for f in candidates if pattern.search(f.url)), None)
        elif step.index is not None and step.index < len(candidates):
            next_frame = candidates[step.index]
        if next_frame is None:
            return None
        frame = next_frame
    return frame


async def _candidates_attr(frame: Frame, strat) -> list[ElementHandle]:
    return await frame.locator(f'[{strat.attr}="{strat.value}"]').element_handles()


async def _candidates_role(frame: Frame, strat) -> list[ElementHandle]:
    return await frame.get_by_role(strat.role, name=strat.name).element_handles()


async def _candidates_text(frame: Frame, strat: TextStrategy) -> list[ElementHandle]:
    return await frame.get_by_text(strat.text, exact=(strat.match == "exact")).element_handles()


async def _candidates_structural(frame: Frame, strat) -> list[ElementHandle]:
    # v0 simplification: `path` is a scoped CSS selector, not a true
    # anchor-relative path. Documented cut — see docs/DECISIONS.md.
    return await frame.locator(strat.path).element_handles()


async def _candidates_visual(frame: Frame, strat) -> list[ElementHandle]:
    # Not implemented in v0 — the last-resort fallback always misses,
    # which is honest: no perceptual matching exists yet.
    return []


async def _candidates_anchor(frame: Frame, strat: AnchorStrategy) -> list[ElementHandle]:
    selector = _CONTROL_SELECTORS.get(strat.control, "*")
    handle = await frame.evaluate_handle(
        _ANCHOR_JS, [strat.text, strat.relation, selector, strat.nth]
    )
    el = handle.as_element()
    return [el] if el else []


async def _candidates_table_cell(frame: Frame, strat: TableCellStrategy) -> list[ElementHandle]:
    handle = await frame.evaluate_handle(_TABLE_CELL_JS, [strat.row_anchor, strat.column_header])
    el = handle.as_element()
    return [el] if el else []


_HANDLERS = {
    "attr": _candidates_attr,
    "role": _candidates_role,
    "anchor": _candidates_anchor,
    "table_cell": _candidates_table_cell,
    "text": _candidates_text,
    "structural": _candidates_structural,
    "visual": _candidates_visual,
}


def _substitute_labels(strat, labels: dict[str, str]):
    if isinstance(strat, AnchorStrategy):
        return strat.model_copy(update={"text": _sub_labels(strat.text, labels)})
    if isinstance(strat, TableCellStrategy):
        return strat.model_copy(
            update={
                "row_anchor": _sub_labels(strat.row_anchor, labels),
                "column_header": _sub_labels(strat.column_header, labels),
            }
        )
    if isinstance(strat, TextStrategy):
        return strat.model_copy(update={"text": _sub_labels(strat.text, labels)})
    return strat


async def _passes_expect(handle: ElementHandle, expect: ElementExpectation) -> bool:
    if expect.kind != "generic":
        selector = _CONTROL_SELECTORS.get(expect.kind)
        if selector and not await handle.evaluate(f"el => el.matches({selector!r})"):
            return False
    if expect.editable is not None:
        is_editable = await handle.evaluate(
            "el => ['INPUT','TEXTAREA','SELECT'].includes(el.tagName) || el.isContentEditable"
        )
        if expect.editable != is_editable:
            return False
    if expect.forbidden_text_pattern:
        text = await handle.evaluate("el => el.innerText || el.value || ''")
        if re.search(expect.forbidden_text_pattern, text):
            return False
    return True


async def resolve(page: Page, target: TargetDescriptor, labels: dict[str, str]) -> Resolution:
    frame = frame_for_scope(page, target.scope)
    if frame is None:
        return Resolution(
            handle=None,
            strategy_used=None,
            confidence=0.0,
            attempts=[
                StrategyAttempt(
                    strategy="<scope>", matched=0, chosen=False, error="frame not found"
                )
            ],
        )

    attempts: list[StrategyAttempt] = []
    for strat in target.strategies:
        resolved_strat = _substitute_labels(strat, labels)
        handler = _HANDLERS[resolved_strat.by]
        try:
            candidates = await handler(frame, resolved_strat)
        except Exception as e:  # noqa: BLE001 — any locator/evaluate failure is a failed attempt
            attempts.append(
                StrategyAttempt(strategy=strat.by, matched=0, chosen=False, error=str(e))
            )
            continue

        valid = [h for h in candidates if await _passes_expect(h, target.expect)]
        if len(valid) == 1:
            attempts.append(StrategyAttempt(strategy=strat.by, matched=1, chosen=True))
            return Resolution(
                handle=valid[0], strategy_used=strat.by, confidence=1.0, attempts=attempts
            )
        if len(valid) == 0:
            attempts.append(StrategyAttempt(strategy=strat.by, matched=0, chosen=False))
        else:
            attempts.append(
                StrategyAttempt(
                    strategy=strat.by, matched=len(valid), chosen=False, error="ambiguous"
                )
            )

    return Resolution(handle=None, strategy_used=None, confidence=0.0, attempts=attempts)
