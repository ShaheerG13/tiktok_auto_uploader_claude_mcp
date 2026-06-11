"""Tests for the TikTok content/init request body builder and token refresh logic."""

from __future__ import annotations

import time

import pytest

from tiktok_slideshow_mcp.config import Settings
from tiktok_slideshow_mcp import tiktok
from tiktok_slideshow_mcp.store import TokenRecord, TokenStore
from tiktok_slideshow_mcp.tiktok import TikTokClient, TikTokError, build_photo_init_body


def test_build_photo_init_body_shape():
    body = build_photo_init_body(
        title="My slideshow",
        description="caption #fyp",
        photo_urls=["https://x/0.jpg", "https://x/1.jpg"],
        cover_index=1,
    )
    assert body["media_type"] == "PHOTO"
    assert body["post_mode"] == "MEDIA_UPLOAD"  # inbox draft
    assert body["post_info"] == {"title": "My slideshow", "description": "caption #fyp"}
    assert body["source_info"]["source"] == "PULL_FROM_URL"
    assert body["source_info"]["photo_images"] == ["https://x/0.jpg", "https://x/1.jpg"]
    assert body["source_info"]["photo_cover_index"] == 1


def test_build_body_validates_limits():
    with pytest.raises(TikTokError, match="at least one"):
        build_photo_init_body("t", "", [], 0)
    with pytest.raises(TikTokError, match="at most 35"):
        build_photo_init_body("t", "", [f"u{i}" for i in range(36)], 0)
    with pytest.raises(TikTokError, match="cover_index"):
        build_photo_init_body("t", "", ["a", "b"], 5)
    with pytest.raises(TikTokError, match="title exceeds"):
        build_photo_init_body("x" * 91, "", ["a"], 0)


def _settings(tmp_path):
    return Settings(
        TIKTOK_CLIENT_KEY="ck",
        TIKTOK_CLIENT_SECRET="cs",
        TIKTOK_REDIRECT_URI="https://x/cb",
        TOKEN_STORE_PATH=str(tmp_path / "tokens.json"),
    )


@pytest.mark.asyncio
async def test_access_token_refreshes_when_expired(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = TokenStore(settings)
    store.save(
        TokenRecord(
            open_id="o1",
            access_token="old",
            refresh_token="rt",
            access_expires_at=time.time() - 10,  # expired
            refresh_expires_at=time.time() + 10_000,
        )
    )

    async def fake_refresh(refresh_token, _settings=None):
        assert refresh_token == "rt"
        return {
            "open_id": "ignored",
            "access_token": "fresh",
            "refresh_token": "rt2",
            "expires_in": 86400,
            "refresh_expires_in": 31536000,
            "scope": "video.upload",
        }

    monkeypatch.setattr(tiktok.oauth, "refresh_tokens", fake_refresh)

    client = TikTokClient(settings=settings, store=store)
    token = await client._access_token("o1")
    assert token == "fresh"
    # New tokens persisted, open_id preserved, still default.
    reloaded = store.get("o1")
    assert reloaded.access_token == "fresh"
    assert reloaded.refresh_token == "rt2"
    assert store.default_open_id() == "o1"


@pytest.mark.asyncio
async def test_no_account_raises(tmp_path):
    client = TikTokClient(settings=_settings(tmp_path), store=TokenStore(_settings(tmp_path)))
    with pytest.raises(TikTokError, match="No connected TikTok account"):
        await client._access_token(None)
