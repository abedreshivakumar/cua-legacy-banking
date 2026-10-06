"""Redacting sensitive text before it's written anywhere persistent
(a transcript, an action log) — the one place discovery/replay output
touches disk, so the one place this has to run. See docs/DECISIONS.md
D26.

Three independent catches, since no single approach covers everything
a legacy banking screen or an LLM's own narration might echo back:
  - fixed-shape patterns (a date-of-birth, a password=... fragment)
  - Luhn-validated digit runs (account/card-shaped numbers — a Luhn
    check, not just "N digits", so an ordinary 16-digit reference
    number that happens to fail the checksum isn't false-flagged)
  - exact literals the caller already knows are sensitive (e.g. every
    value a capability declared as sensitivity="pii"/"secret"), for
    anything the patterns above don't happen to shape-match
"""

import re

_DOB_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PASSWORD_KV_RE = re.compile(r'(?i)"password"\s*:\s*"[^"]*"')
_DIGIT_RUN_RE = re.compile(r"\b\d{12,19}\b")


def luhn_valid(digits: str) -> bool:
    cleaned = digits.replace(" ", "").replace("-", "")
    if not cleaned.isdigit() or len(cleaned) < 12:
        return False
    total = 0
    for i, ch in enumerate(reversed(cleaned)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def redact_text(text: str, *, sensitive_literals: list[str] | None = None) -> str:
    redacted = _SSN_RE.sub("[REDACTED:SSN]", text)
    redacted = _DOB_RE.sub("[REDACTED:DOB]", redacted)
    redacted = _PASSWORD_KV_RE.sub('"password": "[REDACTED:PASSWORD]"', redacted)
    redacted = _DIGIT_RUN_RE.sub(
        lambda m: "[REDACTED:ACCT]" if luhn_valid(m.group(0)) else m.group(0), redacted
    )
    for literal in sensitive_literals or []:
        if literal:
            redacted = redacted.replace(literal, "[REDACTED:DECLARED]")
    return redacted
