"""Reusable detectors for runtime conditions common to this vendor app —
shared across capabilities rather than rediscovered/hand-written per one.
"""

from cua.artifact.conditions import LocationMatches, TextPresent
from cua.artifact.schema import Detector, DismissHandler, ReloginHandler
from cua.artifact.targets import ScopeStep, TargetDescriptor, TextStrategy

# Faults apply to routes like /fr/work/inq/result — content loaded INSIDE
# the "work" frame, not a top-level navigation — so the interstitial's
# "Continue" control lives in that frame, not page.main_frame. Its tag
# varies by how it was triggered (an <a> for a GET, an <input type=submit>
# so a POST's data can be resubmitted) — kept "generic" rather than
# constrained to one, since only one such control exists on this page at
# a time either way, so there's no ambiguity to guard against here.
_CONTINUE_LINK = TargetDescriptor(
    scope=[ScopeStep(name="work")],
    strategies=[TextStrategy(text="Continue", match="exact")],
)


def corebank_mock_detectors() -> list[Detector]:
    """Detectors for faults target_app/faults.py can inject: interstitial,
    session_expire, http500, permission_denied. `slow` needs no detector —
    the existing post-condition timeout/poll already tolerates it."""
    return [
        Detector(
            id="interstitial_notice",
            kind="recoverable",
            when=TextPresent(pattern="SYSTEM NOTICE"),
            active="always",
            priority=20,
            handler=DismissHandler(target=_CONTINUE_LINK, then="resume_step"),
            max_attempts=2,
            origin="library",
        ),
        Detector(
            id="session_expired",
            kind="recoverable",
            when=LocationMatches(route_pattern=r"/login$"),
            active="always",
            priority=30,
            handler=ReloginHandler(script_ref="scripts/corebank_login", then="restart_entry"),
            max_attempts=1,
            origin="library",
        ),
        Detector(
            id="app_error_500",
            kind="hard_failure",
            when=TextPresent(pattern="SYSTEM ERROR"),
            active="always",
            priority=10,
            origin="library",
        ),
        Detector(
            id="permission_denied",
            kind="hard_failure",
            when=TextPresent(pattern="ACCESS DENIED"),
            active="always",
            priority=10,
            origin="library",
        ),
    ]
