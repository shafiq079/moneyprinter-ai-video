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


def _cookie(state, platform="youtube"):
    return ("mpt_fb_" if platform == "facebook" else "mpt_yt_") + hashlib.sha256(
        state.encode()
    ).hexdigest()[:16]


def install_routes(app, provider=accounts, platform="youtube"):
    if platform not in {"youtube", "facebook"}:
        raise ValueError("Unsupported OAuth platform")
    brand = "Facebook" if platform == "facebook" else "YouTube"

    @app.get("/social/" + platform + "/oauth/start")
    async def start(request: Request):
        try:
            url, state, browser = await asyncio.to_thread(
                provider.begin, request.query_params.get("ticket", "")
            )
            response = RedirectResponse(url, status_code=303, headers=HEADERS)
            response.set_cookie(
                _cookie(state, platform),
                browser,
                max_age=600,
                httponly=True,
                secure=provider.settings()["redirect_uri"].startswith("https:"),
                samesite="lax",
                path=provider.CALLBACK,
            )
            return response
        except ValueError:
            return HTMLResponse(
                "Connection request expired or invalid. Return to MoneyPrinter and click Connect "
                + brand
                + " again.",
                status_code=400,
                headers=HEADERS,
            )

    @app.get(provider.CALLBACK)
    async def callback(request: Request):
        state = request.query_params.get("state", "")
        try:
            await asyncio.to_thread(
                provider.finish,
                state,
                request.cookies.get(_cookie(state, platform)),
                request.query_params.get("code"),
                request.query_params.get("error"),
            )
            response = RedirectResponse(
                (
                    "/?view=social&platform=facebook&facebook_connected=1"
                    if platform == "facebook"
                    else "/?view=social&youtube_connected=1"
                ),
                status_code=303,
                headers=HEADERS,
            )
        except ValueError:
            # Never reflect code, state, provider descriptions, or token errors.
            response = HTMLResponse(
                brand
                + " connection was not completed. Return to MoneyPrinter, check the application setup and permissions, and connect again.",
                status_code=400,
                headers=HEADERS,
            )
        response.delete_cookie(_cookie(state, platform), path=provider.CALLBACK)
        return response
