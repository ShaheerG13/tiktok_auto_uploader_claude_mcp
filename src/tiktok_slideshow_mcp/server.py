"""FastMCP server exposing TikTok slideshow tools.

Tools are thin wrappers that delegate to oauth/store/storage/tiktok modules.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from pathlib import Path

from . import oauth
from .config import get_settings
from .storage import R2Uploader
from .store import TokenRecord, TokenStore
from .tiktok import MAX_PHOTOS, TikTokClient

mcp = FastMCP("tiktok-slideshow")

# In-memory store of pending PKCE authorizations, keyed by `state`. Lives for the
# duration of the server process — long enough to bridge start_login -> finish_login.
_pending: dict[str, oauth.PendingAuth] = {}


@mcp.tool()
def start_login() -> str:
    """Begin connecting a TikTok account.

    Returns an authorization URL. Open it in a browser, approve access, then copy the
    full redirect URL (or just the `code` value) and pass it to `finish_login`.
    """
    pending = oauth.build_auth_url()
    _pending[pending.state] = pending
    return (
        "Open this URL in your browser and approve access:\n\n"
        f"{pending.url}\n\n"
        "After approving you'll be redirected to your redirect URI with a `?code=...` "
        "parameter. Copy the full URL (or just the code) and call `finish_login` with it."
    )


@mcp.tool()
async def finish_login(redirect_url_or_code: str) -> str:
    """Complete the TikTok login started by `start_login`.

    Pass either the full redirect URL (recommended) or just the `code` value. Exchanges
    the code for access/refresh tokens and saves them as the default account.
    """
    code = oauth.extract_code(redirect_url_or_code)

    # Match the pending auth by state if the full redirect URL was provided; otherwise
    # fall back to the most recent pending authorization.
    pending = None
    if "state=" in redirect_url_or_code:
        from urllib.parse import urlparse, parse_qs

        states = parse_qs(urlparse(redirect_url_or_code).query).get("state")
        if states:
            pending = _pending.get(states[0])
    if pending is None and _pending:
        pending = next(reversed(_pending.values()))
    if pending is None:
        return "No pending login found. Call `start_login` first, then `finish_login`."

    data = await oauth.exchange_code(code, pending.code_verifier)
    record = TokenRecord.from_token_response(data)
    TokenStore().save(record, make_default=True)
    _pending.pop(pending.state, None)
    return (
        f"Connected TikTok account (open_id {record.open_id[:8]}…). "
        f"Granted scopes: {record.scope or '(none reported)'}. "
        "You can now call `create_slideshow`."
    )


@mcp.tool()
async def list_accounts() -> str:
    """List connected TikTok accounts and verify the default account's connection."""
    store = TokenStore()
    records = store.list()
    if not records:
        return "No TikTok accounts connected. Run `start_login` to connect one."
    default = store.default_open_id()
    lines = []
    for r in records:
        tag = " (default)" if r.open_id == default else ""
        if r.refresh_expired():
            lines.append(f"- open_id {r.open_id[:8]}…{tag}: refresh expired — reconnect")
            continue
        lines.append(f"- open_id {r.open_id[:8]}…{tag}: scopes [{r.scope}]")
    # Confirm the default account works via the basic profile endpoint (user.info.basic).
    try:
        info = await TikTokClient().user_info(default)
        nick = info.get("display_name") or "?"
        lines.append(f"\nDefault account verified: {nick}")
    except Exception as exc:  # noqa: BLE001 — surface as a friendly status line
        lines.append(f"\n(Could not verify default account: {exc})")
    return "Connected accounts:\n" + "\n".join(lines)


@mcp.tool()
async def create_slideshow(
    image_paths: list[str],
    title: str,
    description: str = "",
    cover_index: int = 0,
    account: str | None = None,
) -> str:
    """Create a TikTok photo slideshow and send it to your TikTok inbox as a draft.

    Args:
        image_paths: Local paths to images, in slideshow order (max 35). Images are assumed
            TikTok-ready (JPEG/PNG/WebP, ≤20 MB, ≤1080p) — no resizing is performed.
        title: Post title (max 90 chars). Shown in the TikTok editing flow.
        description: Post description / caption (max 4000 chars). Optional.
        cover_index: 0-based index of the image to use as the cover. Defaults to the first.
        account: Optional open_id to target a specific connected account; defaults to the
            most recently connected one.

    Returns a confirmation with the publish_id. Open the TikTok app inbox to finish posting.
    """
    if not image_paths:
        return "No images supplied."
    if len(image_paths) > MAX_PHOTOS:
        return f"TikTok allows at most {MAX_PHOTOS} images; you supplied {len(image_paths)}."
    missing = [p for p in image_paths if not Path(p).is_file()]
    if missing:
        return "These image files were not found:\n" + "\n".join(f"- {m}" for m in missing)

    # 1) Host images publicly on R2 (TikTok pulls them by URL).
    urls = R2Uploader().upload_slideshow(image_paths)
    # 2) Initialize the MEDIA_UPLOAD photo post -> lands in the inbox as a draft.
    publish_id = await TikTokClient().send_slideshow_to_inbox(
        photo_urls=urls,
        title=title,
        description=description,
        cover_index=cover_index,
        open_id=account,
    )
    return (
        f"✅ Sent slideshow ({len(urls)} photos) to your TikTok inbox as a draft.\n"
        f"publish_id: {publish_id}\n"
        "Open the TikTok app → inbox notification to finish editing and post. "
        "Use `check_status` with the publish_id to track delivery."
    )


@mcp.tool()
async def check_status(publish_id: str, account: str | None = None) -> str:
    """Check the delivery status of a slideshow sent with `create_slideshow`.

    `SEND_TO_USER_INBOX` means the draft is waiting in the TikTok app inbox.
    """
    data = await TikTokClient().post_status(publish_id, account)
    status = data.get("status", "UNKNOWN")
    msg = f"Status for {publish_id}: {status}"
    if data.get("fail_reason"):
        msg += f"\nFail reason: {data['fail_reason']}"
    if status == "SEND_TO_USER_INBOX":
        msg += "\n→ The draft is in your TikTok app inbox, ready to finish and post."
    return msg


def main() -> None:
    # Validate config early for a clearer error than a mid-call failure.
    get_settings()
    mcp.run()


if __name__ == "__main__":
    main()
