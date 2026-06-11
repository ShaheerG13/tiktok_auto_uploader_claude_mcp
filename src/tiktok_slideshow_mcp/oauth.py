"""TikTok OAuth v2 (Login Kit) with PKCE.

Flow:
  1. build_auth_url() -> authorization URL the user opens in a browser (+ PKCE verifier/state).
  2. user authorizes; TikTok redirects to TIKTOK_REDIRECT_URI with `?code=...&state=...`.
  3. exchange_code() swaps the code (+ verifier) for access/refresh tokens.
  4. refresh_tokens() renews an expired access token using the refresh token.

Docs: https://developers.tiktok.com/doc/oauth-user-access-token-management
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, parse_qs

import httpx

from .config import Settings, get_settings

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


class OAuthError(RuntimeError):
    pass


@dataclass
class PendingAuth:
    url: str
    state: str
    code_verifier: str


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_auth_url(settings: Settings | None = None) -> PendingAuth:
    settings = settings or get_settings()
    settings.require_tiktok()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "client_key": settings.tiktok_client_key,
        "scope": ",".join(settings.scope_list),
        "response_type": "code",
        "redirect_uri": settings.tiktok_redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return PendingAuth(
        url=f"{AUTHORIZE_URL}?{urlencode(params)}",
        state=state,
        code_verifier=verifier,
    )


def extract_code(redirect_url_or_code: str) -> str:
    """Accept either a raw `code` value or the full redirect URL and return the code."""
    value = redirect_url_or_code.strip()
    if "code=" in value or value.startswith("http"):
        qs = parse_qs(urlparse(value).query)
        if "error" in qs:
            raise OAuthError(f"Authorization failed: {qs['error'][0]} {qs.get('error_description', [''])[0]}")
        codes = qs.get("code")
        if not codes:
            raise OAuthError("No `code` found in the provided redirect URL.")
        return codes[0]
    return value


async def exchange_code(code: str, code_verifier: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    settings.require_tiktok()
    body = {
        "client_key": settings.tiktok_client_key,
        "client_secret": settings.tiktok_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.tiktok_redirect_uri,
        "code_verifier": code_verifier,
    }
    return await _post_token(body)


async def refresh_tokens(refresh_token: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    settings.require_tiktok()
    body = {
        "client_key": settings.tiktok_client_key,
        "client_secret": settings.tiktok_client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    return await _post_token(body)


async def _post_token(body: dict) -> dict:
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(TOKEN_URL, data=body, headers=headers)
    try:
        data = resp.json()
    except ValueError:
        raise OAuthError(f"Token endpoint returned non-JSON (HTTP {resp.status_code}): {resp.text[:300]}")
    # TikTok returns errors as {"error": "...", "error_description": "..."} at top level.
    if "error" in data and data.get("error") not in (None, "", "ok"):
        raise OAuthError(f"{data.get('error')}: {data.get('error_description', '')}")
    if "access_token" not in data:
        raise OAuthError(f"Unexpected token response: {data}")
    return data
