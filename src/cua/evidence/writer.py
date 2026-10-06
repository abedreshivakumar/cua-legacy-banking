"""Serializing a discovery run to a transcript file under an evidence
root. This is the one place a run's text leaves memory and lands on
disk, so it's the one choke point `safety.redaction.redact_text` has to
run at — see docs/DECISIONS.md D26. A screenshot leaving the same way
goes through `safety.visual_redaction` instead, at capture time, since
text redaction can't touch pixels.
"""

import json
from pathlib import Path

from cua.discovery.loop import DiscoveryResult
from cua.safety.redaction import redact_text


def write_run_transcript(
    result: DiscoveryResult,
    out_dir: Path,
    *,
    sensitive_literals: list[str] | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"run_id: {result.run_id}",
        f"status: {result.status}",
        f"summary: {result.summary}",
        "",
    ]
    for e in result.action_log:
        payload = json.dumps(e.input, sort_keys=True)
        line = f"[step {e.step}] {e.kind}/{e.name}: {payload}"
        if e.text:
            line += f" | {e.text}"
        lines.append(line)

    transcript = redact_text("\n".join(lines), sensitive_literals=sensitive_literals)
    path = out_dir / f"{result.run_id}.transcript.txt"
    path.write_text(transcript)
    return path
