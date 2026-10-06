"""Serializing a discovery run to a transcript file under an evidence
root. This is the one place a run's text leaves memory and lands on
disk, so it's the one choke point `safety.redaction.redact_text` has to
run at — see docs/DECISIONS.md D26. A screenshot leaving the same way
goes through `safety.visual_redaction` instead, at capture time, since
text redaction can't touch pixels.
"""

import json
import shutil
from pathlib import Path

from cua.artifact.schema import Capability
from cua.discovery.loop import DiscoveryResult
from cua.replay.result import RunResult
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


def write_replay_log(
    result: RunResult,
    out_dir: Path,
    *,
    label: str,
    sensitive_literals: list[str] | None = None,
) -> Path:
    """A replay RunResult, redacted the same way a transcript is: its
    `outputs` dict is live data extracted off a real page, so it's
    subject to exactly the same leak risk as discovery's `thinking` text
    (D26), just via a different field."""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = result.model_dump_json(indent=2)
    redacted = redact_text(raw, sensitive_literals=sensitive_literals)
    path = out_dir / f"{label}.{result.run_id}.replay.json"
    path.write_text(redacted)
    return path


def write_screenshot(png_bytes: bytes, out_dir: Path, *, label: str) -> Path:
    """A richer signal than the structured log alone, for the cases that
    most need one: a failure or exceptional state. No text redaction
    applies to an image — a PII-bearing region has to be masked BEFORE
    the screenshot is taken (safety.visual_redaction), not after; this
    function just persists whatever bytes it's given."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{label}.png"
    path.write_bytes(png_bytes)
    return path


def copy_capability(capability: Capability, source_path: Path, out_dir: Path) -> Path:
    """Copies the artifact file itself into the evidence bundle verbatim
    — a capability is already reviewable, nothing in it needs redacting
    (D6's deny-by-default literal handling already keeps raw discovery
    values out of it)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{capability.id}-{capability.version}.yaml"
    shutil.copyfile(source_path, dest)
    return dest
