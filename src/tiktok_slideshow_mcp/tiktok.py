"""TikTok Content Posting API client (photo / slideshow).

Sends slideshows to the creator's inbox as drafts via `post_mode = MEDIA_UPLOAD`, queries
post status, and fetches creator info. Handles transparent access-token refresh.

Endpoints:
  - content init:  POST https://open.tiktokapis.com/v2/post/publish/content/init/
  - status fetch:  POST https://open.tiktokapis.com/v2/post/publish/status/fetch/
  - creator info:  POST https://open.tiktokapis.com/v2/post/publish/creator_info/query/
"""

from __future__ import annotations

import httpx

from . import oauth
from .config import Settings, get_settings
from .store import TokenRecord, TokenStore

API_BASE = "https://open.tiktokapis.com"
CONTENT_INIT_URL = f"{API_BASE}/v2/post/publish/content/init/"
STATUS_FETCH_URL = f"{API_BASE}/v2/post/publish/status/fetch/"
CREATOR_INFO_URL = f"{API_BASE}/v2/post/publish/creator_info/query/"
USER_INFO_URL = f"{API_BASE}/v2/user/info/"

# TikTok limits.
MAX_PHOTOS = 35
MAX_TITLE_LEN = 90
MAX_DESC_LEN = 4000


class TikTokError(RuntimeError):
    pass


def build_photo_init_body(
    title: str,
    description: str,
    photo_urls: list[str],
    cover_index: int = 0,
    post_mode: str = "MEDIA_UPLOAD",
) -> dict:
    """Build the request body for a photo `content/init` call.

    Pure function (no I/O) so the exact request shape can be unit-tested. `MEDIA_UPLOAD`
    sends the slideshow to the creator's inbox as a draft.
    """
    if not photo_urls:
        raise TikTokError("photo_urls must contain at least one URL.")
    if len(photo_urls) > MAX_PHOTOS:
        raise TikTokError(f"TikTok allows at most {MAX_PHOTOS} photos; got {len(photo_urls)}.")
    if not 0 <= cover_index < len(photo_urls):
        raise TikTokError(f"cover_index {cover_index} out of range for {len(photo_urls)} photos.")
    if len(title) > MAX_TITLE_LEN:
        raise TikTokError(f"title exceeds {MAX_TITLE_LEN} characters.")
    if len(description) > MAX_DESC_LEN:
        raise TikTokError(f"description exceeds {MAX_DESC_LEN} characters.")

    return {
        "media_type": "PHOTO",
        "post_mode": post_mode,
        "post_info": {
            "title": title,
            "description": description,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_images": photo_urls,
            "photo_cover_index": cover_index,
        },
    }


def _raise_for_tiktok_error(data: dict) -> None:
    """TikTok wraps status in an `error` object: code 'ok' means success."""
    err = data.get("error") or {}
    code = err.get("code")
    if code and code != "ok":
        raise TikTokError(
            f"TikTok API error [{code}]: {err.get('message', '')} "
            f"(log_id {err.get('log_id', '?')})"
        )


class TikTokClient:
    def __init__(self, settings: Settings | None = None, store: TokenStore | None = None):
        self.settings = settings or get_settings()
        self.store = store or TokenStore(self.settings)

    async def _access_token(self, open_id: str | None) -> str:
        record = self.store.get(open_id)
        if record is None:
            raise TikTokError("No connected TikTok account. Run `start_login` first.")
        if record.refresh_expired():
            raise TikTokError(
                "Refresh token expired — reconnect the account with `start_login`."
            )
        if record.access_expired():
            record = await self._refresh(record)
        return record.access_token

    async def _refresh(self, record: TokenRecord) -> TokenRecord:
        data = await oauth.refresh_tokens(record.refresh_token, self.settings)
        # open_id is stable across refresh; preserve default flag.
        is_default = self.store.default_open_id() == record.open_id
        new_record = TokenRecord.from_token_response({**data, "open_id": record.open_id})
        new_record.nickname = record.nickname
        self.store.save(new_record, make_default=is_default)
        return new_record

    async def _post(self, url: str, body: dict, open_id: str | None) -> dict:
        token = await self._access_token(open_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body, headers=headers)
        if resp.status_code == 429:
            raise TikTokError("Rate limited by TikTok (max 6 requests/min per account). Try again shortly.")
        try:
            data = resp.json()
        except ValueError:
            raise TikTokError(f"Non-JSON response (HTTP {resp.status_code}): {resp.text[:300]}")
        _raise_for_tiktok_error(data)
        return data

    async def user_info(self, open_id: str | None = None) -> dict:
        """Fetch basic profile (display name) using the user.info.basic scope.

        Used to confirm a connection works without needing the heavier video.publish scope
        that creator_info requires.
        """
        token = await self._access_token(open_id)
        headers = {"Authorization": f"Bearer {token}"}
        params = {"fields": "open_id,display_name"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(USER_INFO_URL, params=params, headers=headers)
        try:
            data = resp.json()
        except ValueError:
            raise TikTokError(f"Non-JSON response (HTTP {resp.status_code}): {resp.text[:300]}")
        _raise_for_tiktok_error(data)
        return data.get("data", {}).get("user", {})

    async def creator_info(self, open_id: str | None = None) -> dict:
        """Query creator posting options. Requires the video.publish scope (DIRECT_POST flow)."""
        data = await self._post(CREATOR_INFO_URL, {}, open_id)
        return data.get("data", {})

    async def send_slideshow_to_inbox(
        self,
        photo_urls: list[str],
        title: str,
        description: str = "",
        cover_index: int = 0,
        open_id: str | None = None,
    ) -> str:
        """Initialize a MEDIA_UPLOAD photo post; returns the publish_id."""
        body = build_photo_init_body(title, description, photo_urls, cover_index)
        data = await self._post(CONTENT_INIT_URL, body, open_id)
        publish_id = data.get("data", {}).get("publish_id")
        if not publish_id:
            raise TikTokError(f"No publish_id returned: {data}")
        return publish_id

    async def post_status(self, publish_id: str, open_id: str | None = None) -> dict:
        data = await self._post(STATUS_FETCH_URL, {"publish_id": publish_id}, open_id)
        return data.get("data", {})
