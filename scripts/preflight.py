"""Preflight check: validate .env config and verify R2 hosting end-to-end.

Run:  python scripts/preflight.py

It uploads a tiny test object to R2 and fetches it back over your public custom domain to
confirm images will be reachable by TikTok. No secrets are printed.
"""

from __future__ import annotations

import sys
import uuid

import httpx

from tiktok_slideshow_mcp.config import get_settings
from tiktok_slideshow_mcp.storage import R2Uploader


def _mask(present: bool) -> str:
    return "OK" if present else "MISSING"


def main() -> int:
    s = get_settings()

    print("== Config ==")
    print(f"  TIKTOK_CLIENT_KEY      {_mask(bool(s.tiktok_client_key))}")
    print(f"  TIKTOK_CLIENT_SECRET   {_mask(bool(s.tiktok_client_secret))}")
    print(f"  TIKTOK_REDIRECT_URI    {s.tiktok_redirect_uri or 'MISSING'}")
    print(f"  TIKTOK_SCOPES          {','.join(s.scope_list)}")
    print(f"  R2_ACCOUNT_ID          {_mask(bool(s.r2_account_id))}")
    print(f"  R2_ACCESS_KEY_ID       {_mask(bool(s.r2_access_key_id))}")
    print(f"  R2_SECRET_ACCESS_KEY   {_mask(bool(s.r2_secret_access_key))}")
    print(f"  R2_BUCKET              {s.r2_bucket or 'MISSING'}")
    print(f"  R2_PUBLIC_BASE_URL     {s.r2_public_base_url or 'MISSING'}")

    try:
        s.require_tiktok()
        s.require_r2()
    except RuntimeError as exc:
        print(f"\n[FAIL] {exc}")
        return 1

    print("\n== R2 round-trip ==")
    key = f"preflight/{uuid.uuid4().hex}.txt"
    body = b"tiktok-slideshow-mcp preflight ok"
    try:
        up = R2Uploader(settings=s)
        up._client.put_object(Bucket=s.r2_bucket, Key=key, Body=body, ContentType="text/plain")
        url = f"{s.r2_public_base_url.rstrip('/')}/{key}"
        print(f"  Uploaded test object, fetching: {url}")
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        if resp.status_code == 200 and resp.content == body:
            print("  [OK] Public custom domain serves R2 objects correctly.")
            ok = True
        else:
            print(f"  [FAIL] Got HTTP {resp.status_code}. The custom domain may not be mapped/active yet.")
            print("         Check R2 bucket > Settings > Custom Domains shows 'Active'.")
            ok = False
        # Clean up the test object.
        up._client.delete_object(Bucket=s.r2_bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] R2 error: {exc}")
        print("         Check R2_ACCOUNT_ID and that the API token has read/write on the bucket.")
        return 1

    if not ok:
        return 1

    print("\nAll preflight checks passed. Next: connect your TikTok account with `start_login`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
