"""Seed member data, session store, and UI label strings."""

import json
import secrets
from dataclasses import dataclass
from pathlib import Path

SEED_PATH = Path(__file__).parent / "seed.json"


@dataclass
class Member:
    member_no: str
    name: str
    status: str
    savings_balance: str
    ssn_display: str
    dob: str
    last_activity: str


def _load_members() -> dict[str, Member]:
    raw = json.loads(SEED_PATH.read_text())
    return {m["member_no"]: Member(**m) for m in raw}


MEMBERS: dict[str, Member] = _load_members()


def find_member(member_no: str) -> Member | None:
    return MEMBERS.get(member_no)


# Two label sets: the base vendor-product wording, and a relabeled "tenant B"
# variant used by the relabel fault to exercise drift/override handling later.
LABELS_BASE = {
    "member_id_label": "Member No.:",
    "nav_inquiry": "Member Inquiry",
    "search_btn": "Search",
    "savings_row": "Regular Savings",
    "balance_col": "Available Balance",
}
LABELS_RELABELED = {
    "member_id_label": "Acct Holder ID:",
    "nav_inquiry": "Find Member",
    "search_btn": "Find",
    "savings_row": "Share Savings",
    "balance_col": "Current Balance",
}


# --- sessions -----------------------------------------------------------
# In-memory only; this is a mock app, not a real auth system.


@dataclass
class Session:
    username: str


SESSIONS: dict[str, Session] = {}


def create_session(username: str) -> str:
    token = secrets.token_hex(16)
    SESSIONS[token] = Session(username=username)
    return token


def get_session(token: str | None) -> Session | None:
    if token is None:
        return None
    return SESSIONS.get(token)


def invalidate_session(token: str) -> None:
    SESSIONS.pop(token, None)


# --- transfers ------------------------------------------------------------
# In-memory, session-scoped staging for the one irreversible write this app
# exposes: a funds transfer. stage -> confirm -> commit mirrors the real
# three-page flow (review, warning, receipt) so there's a genuine POST to
# gate behind an approval, not a synthetic stand-in.


@dataclass
class PendingTransfer:
    from_share: str
    to_share: str
    amount: str
    memo: str


PENDING_TRANSFERS: dict[str, PendingTransfer] = {}


def stage_transfer(token: str, *, from_share: str, to_share: str, amount: str, memo: str) -> None:
    PENDING_TRANSFERS[token] = PendingTransfer(
        from_share=from_share, to_share=to_share, amount=amount, memo=memo
    )


def get_pending_transfer(token: str) -> PendingTransfer | None:
    return PENDING_TRANSFERS.get(token)


def commit_transfer(token: str) -> str:
    """The actual irreversible side effect: clears the staged transfer and
    returns a confirmation number. Idempotent-unsafe by design — calling
    this twice for the same token is exactly the double-spend this app's
    policy gate exists to prevent at the replay layer, not here."""
    PENDING_TRANSFERS.pop(token, None)
    return "CNF" + secrets.token_hex(4).upper()
