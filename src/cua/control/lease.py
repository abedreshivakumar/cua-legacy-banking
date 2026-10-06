"""A control lease: tracks who currently drives a live discovery session
— the agent, or a human who's taken over after a `request_human` escalation.

File-based on purpose: the discovery loop and a separate terminal
operator process (S14's other half, control/operator.py and the `cua
control` CLI) don't share any Python state — the lease file is the only
thing between them. Async waiting is a poll loop, not a filesystem
watch, for the same reason the rest of this codebase polls for a
condition rather than subscribing to one (replay/steps.py's wait_for):
it's one obvious mechanism reused everywhere, not two.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LeaseState = Literal["agent", "human"]

_POLL_S = 0.2


@dataclass
class ControlLease:
    path: Path

    def _read(self) -> dict:
        if not self.path.exists():
            return {"state": "agent", "reason": None, "updated_at": time.time()}
        return json.loads(self.path.read_text())

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))

    @property
    def state(self) -> LeaseState:
        return self._read()["state"]  # type: ignore[no-any-return]

    @property
    def reason(self) -> str | None:
        return self._read()["reason"]  # type: ignore[no-any-return]

    def hand_to_human(self, reason: str) -> None:
        self._write({"state": "human", "reason": reason, "updated_at": time.time()})

    def release_to_agent(self) -> None:
        self._write({"state": "agent", "reason": None, "updated_at": time.time()})

    async def wait_for_release(self, *, timeout_s: float) -> bool:
        """Blocks the current coroutine until a human releases the lease
        back to the agent. Returns False on timeout — the caller decides
        what "a human never showed up" means for the run."""
        start = time.monotonic()
        while self.state == "human":
            if time.monotonic() - start > timeout_s:
                return False
            await asyncio.sleep(_POLL_S)
        return True
