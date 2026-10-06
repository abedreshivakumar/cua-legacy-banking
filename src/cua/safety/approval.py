"""Single-use approval records that gate a commit-capable replay.

A record is keyed by (capability id, version, effective content hash,
canonicalized inputs) — not just capability id — so an approval granted
for one specific call can't be replayed against a different amount or
account, and a stale approval from an edited artifact version never
silently applies to the new one. See docs/DECISIONS.md D23.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

ApprovalDecision = Literal["approved", "pending", "reused"]


def approval_key(
    capability_id: str, version: str, effective_sha256: str, inputs: dict[str, Any]
) -> str:
    canon = json.dumps(inputs, sort_keys=True, default=str)
    digest = hashlib.sha256(canon.encode()).hexdigest()
    return f"{capability_id}:{version}:{effective_sha256}:{digest}"


@dataclass
class ApprovalStore:
    _records: dict[str, Literal["approved", "consumed"]] = field(default_factory=dict)

    def grant(self, key: str) -> None:
        self._records[key] = "approved"

    def decide(self, key: str) -> ApprovalDecision:
        """Checks AND consumes in one step — a record can back exactly one
        commit attempt, so there is no window between "check" and "use"
        for a second concurrent replay to also observe "approved"."""
        status = self._records.get(key)
        if status is None:
            return "pending"
        if status == "consumed":
            return "reused"
        self._records[key] = "consumed"
        return "approved"
