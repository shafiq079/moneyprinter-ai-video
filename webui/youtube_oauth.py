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
    prefix = {"youtube": "mpt_yt_", "facebook": "mpt_fb_", "tiktok": "mpt_tt_"}[platform]
    return prefix + hashlib.sha256(state.encode()).hexdigest()[:16]


def install_routes(app, provider=accounts, platform="youtube"):
    if platform not in {"youtube", "facebook", "tiktok"}:
        raise ValueError("Unsupported OAuth platform")
    brand = {"youtube": "YouTube", "facebook": "Facebook", "tiktok": "TikTok"}[platform]

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
            result = await asyncio.to_thread(
                provider.finish,
                state,
                request.cookies.get(_cookie(state, platform)),
                request.query_params.get("code"),
                request.query_params.get("error"),
            )
            destination = platform
            if platform == "facebook" and isinstance(result, str) and result.startswith("instagram:"):
                destination = "instagram"
            location = (
                "/?view=social&youtube_connected=1" if destination == "youtube"
                else f"/?view=social&platform={destination}&{destination}_connected=1"
            )
            response = RedirectResponse(
                location,
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
