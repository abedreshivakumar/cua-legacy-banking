"""The mock legacy core-banking web UI.

A deliberately hostile server-rendered app: a frameset shell, nested-table
layouts, no ids or test attributes, generic markup. Faults are injected only
through POST /__faults, a route the discovery/replay agent is never allowed
to reach (it sits outside the agent's allowlist).
"""

import asyncio
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from target_app.data import (
    commit_transfer,
    create_session,
    find_member,
    get_pending_transfer,
    get_session,
    invalidate_session,
    stage_transfer,
)
from target_app.faults import FaultController, FaultSpec

load_dotenv()  # so `make app`/`uvicorn target_app.app:app` picks up .env on its own

app = FastAPI(title="CoreBank (mock)")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
faults = FaultController()

COOKIE_NAME = "corebank_session"


def _labels() -> dict[str, str]:
    from target_app.data import LABELS_BASE, LABELS_RELABELED

    return LABELS_RELABELED if faults.relabeled else LABELS_BASE


async def _apply_route_faults(
    request: Request, token: str
) -> HTMLResponse | RedirectResponse | None:
    """Run the faults registered for this path. Returns a response to
    short-circuit with, or None to proceed normally."""
    spec = faults.consume(request.url.path)
    if spec is None:
        return None

    if spec.kind == "slow":
        await asyncio.sleep(spec.slow_ms / 1000)
        return None

    if spec.kind == "interstitial":
        # A plain <a href> Continue link only works for a GET-triggered
        # interstitial — a POST-triggered one (e.g. the search submit) needs
        # its original form data resubmitted, or Continue 405s against a
        # POST-only route. Found by actually replaying a recovery, not by
        # inspection — see docs/DECISIONS.md.
        form_fields: dict[str, str] | None = None
        if request.method == "POST":
            form = await request.form()
            form_fields = {k: str(v) for k, v in form.items()}
        return templates.TemplateResponse(
            request,
            "interstitial.html",
            {
                "continue_url": str(request.url),
                "continue_method": request.method,
                "form_fields": form_fields,
            },
        )

    if spec.kind == "http500":
        return templates.TemplateResponse(request, "error_500.html", {}, status_code=500)

    if spec.kind == "permission_denied":
        return templates.TemplateResponse(request, "error_403.html", {}, status_code=403)

    if spec.kind == "session_expire":
        invalidate_session(token)
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE_NAME)
        return resp

    return None


def _require_session(request: Request) -> tuple[str | None, RedirectResponse | None]:
    """Returns (session_token, redirect_if_unauthenticated)."""
    token = request.cookies.get(COOKIE_NAME)
    if get_session(token) is None:
        return None, RedirectResponse("/login", status_code=303)
    return token, None


# --- auth -----------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login")
async def login_submit(username: str = Form(...), password: str = Form(...)) -> RedirectResponse:
    expected_user = os.environ.get("COREBANK_USER", "teller1")
    expected_pass = os.environ.get("COREBANK_PASSWORD", "")
    if username != expected_user or password != expected_pass:
        resp = RedirectResponse("/login?error=1", status_code=303)
        return resp
    token = create_session(username)
    resp = RedirectResponse("/main", status_code=303)
    resp.set_cookie(COOKIE_NAME, token, httponly=True)
    return resp


# --- frameset shell ---------------------------------------------------------


@app.get("/main", response_class=HTMLResponse)
async def main_frameset(request: Request) -> HTMLResponse:
    _, redirect = _require_session(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "frameset.html", {})


@app.get("/fr/top", response_class=HTMLResponse)
async def frame_top(request: Request) -> HTMLResponse:
    _, redirect = _require_session(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "banner.html", {})


@app.get("/fr/menu", response_class=HTMLResponse)
async def frame_menu(request: Request) -> HTMLResponse:
    _, redirect = _require_session(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "nav.html", {"labels": _labels()})


# --- member inquiry ----------------------------------------------------------


@app.get("/fr/work/inq", response_class=HTMLResponse)
async def inquiry_form(request: Request) -> HTMLResponse:
    token, redirect = _require_session(request)
    if redirect:
        return redirect
    fault_resp = await _apply_route_faults(request, token)  # type: ignore[arg-type]
    if fault_resp:
        return fault_resp
    return templates.TemplateResponse(request, "inquiry_form.html", {"labels": _labels()})


@app.post("/fr/work/inq/result", response_class=HTMLResponse)
async def inquiry_result(request: Request, member_no: str = Form(...)) -> HTMLResponse:
    token, redirect = _require_session(request)
    if redirect:
        return redirect
    fault_resp = await _apply_route_faults(request, token)  # type: ignore[arg-type]
    if fault_resp:
        return fault_resp

    member = find_member(member_no.strip())
    return templates.TemplateResponse(
        request,
        "inquiry_result.html",
        {"labels": _labels(), "member": member, "queried_member_no": member_no.strip()},
    )


# --- transfer (the one irreversible write; gated by the safety policy at
# the replay layer, not here — this route will happily commit anything it's
# asked to, same as a real legacy teller app would) -------------------------


@app.get("/fr/work/xfer", response_class=HTMLResponse)
async def xfer_form(request: Request) -> HTMLResponse:
    _, redirect = _require_session(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "xfer_form.html", {})


@app.post("/fr/work/xfer/review", response_class=HTMLResponse)
async def xfer_review(
    request: Request,
    from_share: str = Form(...),
    to_share: str = Form(...),
    amount: str = Form(...),
    memo: str = Form(""),
) -> HTMLResponse:
    token, redirect = _require_session(request)
    if redirect:
        return redirect
    stage_transfer(token, from_share=from_share, to_share=to_share, amount=amount, memo=memo)  # type: ignore[arg-type]
    return templates.TemplateResponse(
        request,
        "xfer_review.html",
        {"from_share": from_share, "to_share": to_share, "amount": amount},
    )


@app.post("/fr/work/xfer/confirm", response_class=HTMLResponse)
async def xfer_confirm(request: Request) -> HTMLResponse:
    token, redirect = _require_session(request)
    if redirect:
        return redirect
    if get_pending_transfer(token) is None:  # type: ignore[arg-type]
        return RedirectResponse("/fr/work/xfer", status_code=303)
    return templates.TemplateResponse(request, "xfer_confirm.html", {})


@app.post("/fr/work/xfer/receipt", response_class=HTMLResponse)
async def xfer_receipt(request: Request) -> HTMLResponse:
    token, redirect = _require_session(request)
    if redirect:
        return redirect
    pending = get_pending_transfer(token)  # type: ignore[arg-type]
    if pending is None:
        return RedirectResponse("/fr/work/xfer", status_code=303)
    confirmation_no = commit_transfer(token)  # type: ignore[arg-type]
    return templates.TemplateResponse(
        request, "xfer_receipt.html", {"confirmation_no": confirmation_no}
    )


# --- fault admin (outside the agent's allowlist) ----------------------------


@app.post("/__faults")
async def register_fault(
    kind: str = Form(...),
    mode: str = Form("once"),
    routes: str = Form(""),  # comma-separated path prefixes
    slow_ms: int = Form(0),
) -> dict:
    route_list = [r.strip() for r in routes.split(",") if r.strip()]
    faults.register(FaultSpec(kind=kind, routes=route_list, mode=mode, slow_ms=slow_ms))  # type: ignore[arg-type]
    return {"ok": True, "kind": kind, "mode": mode, "routes": route_list}


@app.delete("/__faults")
async def clear_faults() -> dict:
    faults.reset()
    return {"ok": True}


@app.get("/__health")
async def health() -> dict:
    return {"ok": True, "t": time.time()}
