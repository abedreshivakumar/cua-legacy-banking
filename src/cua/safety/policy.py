"""The act() choke point: a network-level guard installed on the replay
page before any step runs. This is the ONE place a capability's outgoing
traffic is inspected for side-effect risk — not scattered through step
dispatch — see docs/DECISIONS.md D22.

Installed via `page.route("**/*", ...)`, which sees every request
regardless of what triggered it: an explicit `page.goto`, a clicked
link (including a `javascript:` href, which Playwright still turns into
a navigation request through this same pipe), or a plain form submit
fired by pressing Enter in a field — a Return-key submit and a button
click produce the identical POST, so there is no separate "was it Enter"
classification to get wrong (see D23).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from playwright.async_api import Page, Route

ViolationKind = Literal[
    "disallowed_scheme",
    "off_origin",
    "commit_blocked_read_only",
    "commit_pending_approval",
    "commit_reused_approval",
]

CommitDecision = Literal["approved", "pending", "reused"]


@dataclass
class PolicyConfig:
    allowed_origins: list[str]
    commit_routes: list[str] = field(default_factory=list)


@dataclass
class PolicyViolation:
    kind: ViolationKind
    url: str


@dataclass
class PolicyState:
    violations: list[PolicyViolation] = field(default_factory=list)
    committed_urls: list[str] = field(default_factory=list)

    def latest(self) -> PolicyViolation | None:
        return self.violations[-1] if self.violations else None


def _is_commit_path(path: str, commit_routes: list[str]) -> bool:
    return any(path.startswith(prefix) for prefix in commit_routes)


async def install_policy_guard(
    page: Page,
    config: PolicyConfig,
    state: PolicyState,
    *,
    side_effects: Literal["read_only", "reversible_write", "irreversible_write"],
    decide_commit: Callable[[], CommitDecision] | None,
) -> None:
    async def handler(route: Route) -> None:
        url = route.request.url
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https"):
            state.violations.append(PolicyViolation("disallowed_scheme", url))
            await route.abort()
            return
        if f"{parsed.scheme}://{parsed.netloc}" not in config.allowed_origins:
            state.violations.append(PolicyViolation("off_origin", url))
            await route.abort()
            return

        if route.request.method == "POST" and _is_commit_path(parsed.path, config.commit_routes):
            if side_effects == "read_only":
                state.violations.append(PolicyViolation("commit_blocked_read_only", url))
                await route.abort()
                return
            decision = decide_commit() if decide_commit else "pending"
            if decision == "pending":
                state.violations.append(PolicyViolation("commit_pending_approval", url))
                await route.abort()
                return
            if decision == "reused":
                state.violations.append(PolicyViolation("commit_reused_approval", url))
                await route.abort()
                return
            state.committed_urls.append(url)

        await route.continue_()

    await page.route("**/*", handler)
