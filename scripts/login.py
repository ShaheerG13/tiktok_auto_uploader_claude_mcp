"""Interactive TikTok login helper.

Run:  python scripts/login.py

Opens the TikTok authorization page in your browser, waits for you to paste the redirect
URL back, exchanges it for tokens, and saves them so the MCP server can post on your behalf.
"""

from __future__ import annotations

import asyncio
import webbrowser

from tiktok_slideshow_mcp import oauth
from tiktok_slideshow_mcp.store import TokenRecord, TokenStore
from tiktok_slideshow_mcp.tiktok import TikTokClient


async def main() -> int:
    pending = oauth.build_auth_url()
    print("Opening your browser to authorize TikTok...\n")
    print(pending.url + "\n")
    try:
        webbrowser.open(pending.url)
    except Exception:
        print("(Could not auto-open a browser — copy the URL above manually.)")

    print(
        "After you approve, your browser will land on a page starting with\n"
        "  https://tt-media.sakinastreetwear.com/oauth/callback?code=...\n"
        "(it will show a 'not found' error — that's expected). Copy the FULL URL from the\n"
        "address bar and paste it below.\n"
    )
    redirect = input("Paste the redirect URL (or just the code): ").strip()
    if not redirect:
        print("Nothing pasted — aborting.")
        return 1

    code = oauth.extract_code(redirect)
    data = await oauth.exchange_code(code, pending.code_verifier)
    record = TokenRecord.from_token_response(data)
    TokenStore().save(record, make_default=True)
    print(f"\n[OK] Connected. Granted scopes: {record.scope or '(none reported)'}")

    # Confirm the connection using the basic profile endpoint (works with user.info.basic).
    try:
        info = await TikTokClient().user_info(record.open_id)
        nick = info.get("display_name") or "?"
        print(f"[OK] Verified account: {nick}")
    except Exception as exc:  # noqa: BLE001
        print(f"(Could not verify account: {exc})")

    print("\nDone. You can now create slideshows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
