"""Browser-bound OAuth handoff on the same public gateway as Streamlit."""

import asyncio
import hashlib

from fastapi import Request
from starlette.responses import HTMLResponse, RedirectResponse

from app.services import youtube_accounts as accounts

HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _cookie(state):
    return "mpt_yt_" + hashlib.sha256(state.encode()).hexdigest()[:16]


def install_routes(app):
    @app.get("/social/youtube/oauth/start")
    async def start(request: Request):
        try:
            url, state, browser = await asyncio.to_thread(
                accounts.begin, request.query_params.get("ticket", "")
            )
            response = RedirectResponse(url, status_code=303, headers=HEADERS)
            response.set_cookie(
                _cookie(state),
                browser,
                max_age=600,
                httponly=True,
                secure=accounts.settings()["redirect_uri"].startswith("https:"),
                samesite="lax",
                path=accounts.CALLBACK,
            )
            return response
        except ValueError:
            return HTMLResponse(
                "Connection request expired or invalid. Return to MoneyPrinter and click Connect YouTube again.",
                status_code=400,
                headers=HEADERS,
            )

    @app.get(accounts.CALLBACK)
    async def callback(request: Request):
        state = request.query_params.get("state", "")
        try:
            await asyncio.to_thread(
                accounts.finish,
                state,
                request.cookies.get(_cookie(state)),
                request.query_params.get("code"),
                request.query_params.get("error"),
            )
            response = RedirectResponse(
                "/?view=social&youtube_connected=1", status_code=303, headers=HEADERS
            )
        except ValueError:
            # Never reflect code, state, provider descriptions, or token errors.
            response = HTMLResponse(
                "YouTube connection was not completed. Return to MoneyPrinter, check the Google app setup and permissions, and connect again.",
                status_code=400,
                headers=HEADERS,
            )
        response.delete_cookie(_cookie(state), path=accounts.CALLBACK)
        return response
