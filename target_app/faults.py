"""In-memory fault injection, toggled via POST /__faults.

Faults fire on route match, in one of three modes:
  once   — fires on the next matching request, then removes itself
  always — fires on every matching request
  nth:k  — fires only on the k-th matching request
"""

from dataclasses import dataclass, field
from typing import Literal

FaultKind = Literal[
    "interstitial", "slow", "http500", "permission_denied", "relabel", "session_expire"
]


@dataclass
class FaultSpec:
    kind: FaultKind
    routes: list[str]  # path prefixes this fault applies to
    mode: str = "once"  # "once" | "always" | "nth:<k>"
    slow_ms: int = 0
    hit_count: int = 0


@dataclass
class FaultController:
    specs: list[FaultSpec] = field(default_factory=list)
    relabeled: bool = False

    def register(self, spec: FaultSpec) -> None:
        if spec.kind == "relabel":
            self.relabeled = True
            return
        self.specs.append(spec)

    def reset(self) -> None:
        self.specs.clear()
        self.relabeled = False

    def consume(self, path: str) -> FaultSpec | None:
        """Check faults registered for this path; if one fires, consume it
        (removing it if its budget is exhausted) and return it."""
        for spec in list(self.specs):
            if not any(path.startswith(route) for route in spec.routes):
                continue
            spec.hit_count += 1
            if spec.mode == "once":
                self.specs.remove(spec)
                return spec
            if spec.mode == "always":
                return spec
            if spec.mode.startswith("nth:"):
                target = int(spec.mode.split(":", 1)[1])
                if spec.hit_count == target:
                    self.specs.remove(spec)
                    return spec
                continue
        return None
