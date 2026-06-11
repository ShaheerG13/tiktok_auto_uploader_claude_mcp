"""Tests for PKCE auth URL construction, code extraction, and token persistence."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import pytest

from tiktok_slideshow_mcp.config import Settings
from tiktok_slideshow_mcp import oauth
from tiktok_slideshow_mcp.store import TokenRecord, TokenStore


def _settings(tmp_path):
    return Settings(
        TIKTOK_CLIENT_KEY="ck",
        TIKTOK_CLIENT_SECRET="cs",
        TIKTOK_REDIRECT_URI="https://tt-media.example.com/oauth/callback",
        TOKEN_STORE_PATH=str(tmp_path / "tokens.json"),
    )


def test_build_auth_url_has_pkce_and_scopes(tmp_path):
    pending = oauth.build_auth_url(_settings(tmp_path))
    qs = parse_qs(urlparse(pending.url).query)
    assert qs["client_key"] == ["ck"]
    assert qs["response_type"] == ["code"]
    assert qs["code_challenge_method"] == ["S256"]
    assert "video.upload" in qs["scope"][0]
    assert qs["state"] == [pending.state]
    # challenge must not equal verifier (it's the S256 hash, base64url, unpadded)
    assert qs["code_challenge"][0] != pending.code_verifier
    assert "=" not in qs["code_challenge"][0]


def test_extract_code_from_url_and_raw():
    url = "https://tt-media.example.com/oauth/callback?code=ABC123&state=xyz"
    assert oauth.extract_code(url) == "ABC123"
    assert oauth.extract_code("ABC123") == "ABC123"


def test_extract_code_surfaces_error():
    url = "https://x/cb?error=access_denied&error_description=user+denied"
    with pytest.raises(oauth.OAuthError, match="access_denied"):
        oauth.extract_code(url)


def test_token_store_roundtrip_and_default(tmp_path):
    store = TokenStore(_settings(tmp_path))
    rec = TokenRecord.from_token_response(
        {
            "open_id": "open-123",
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 86400,
            "refresh_expires_in": 31536000,
            "scope": "video.upload",
        }
    )
    store.save(rec)
    got = store.get()
    assert got is not None
    assert got.open_id == "open-123"
    assert store.default_open_id() == "open-123"
    assert not got.access_expired()
    assert not got.refresh_expired()


def test_access_expired_detection(tmp_path):
    rec = TokenRecord(
        open_id="o",
        access_token="a",
        refresh_token="r",
        access_expires_at=time.time() - 5,
        refresh_expires_at=time.time() + 1000,
    )
    assert rec.access_expired()
    assert not rec.refresh_expired()
