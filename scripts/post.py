"""Post a slideshow to your TikTok inbox from the command line.

Usage:
  python scripts/post.py "My title" image1.jpg image2.jpg [image3.png ...]
  python scripts/post.py "My title" --description "caption #fyp" --cover 0 img1.jpg img2.jpg

Uploads the images to R2 and sends the slideshow to your TikTok inbox as a draft, then
polls delivery status. Open the TikTok app to finish editing and post.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from tiktok_slideshow_mcp.storage import R2Uploader
from tiktok_slideshow_mcp.tiktok import TikTokClient


async def main() -> int:
    ap = argparse.ArgumentParser(description="Send a TikTok slideshow to your inbox.")
    ap.add_argument("title", help="Post title (max 90 chars).")
    ap.add_argument("images", nargs="+", help="Image file paths, in slideshow order.")
    ap.add_argument("--description", default="", help="Caption/description (max 4000 chars).")
    ap.add_argument("--cover", type=int, default=0, help="0-based cover image index.")
    args = ap.parse_args()

    missing = [p for p in args.images if not Path(p).is_file()]
    if missing:
        print("These files were not found:")
        for m in missing:
            print(f"  - {m}")
        return 1

    print(f"Uploading {len(args.images)} image(s) to R2...")
    urls = R2Uploader().upload_slideshow(args.images)
    for u in urls:
        print(f"  {u}")

    print("\nSending to TikTok inbox (MEDIA_UPLOAD)...")
    client = TikTokClient()
    publish_id = await client.send_slideshow_to_inbox(
        photo_urls=urls,
        title=args.title,
        description=args.description,
        cover_index=args.cover,
    )
    print(f"[OK] publish_id: {publish_id}")

    print("\nChecking delivery status...")
    for _ in range(6):
        data = await client.post_status(publish_id)
        status = data.get("status", "UNKNOWN")
        print(f"  status: {status}")
        if status in ("SEND_TO_USER_INBOX", "FAILED"):
            if status == "FAILED":
                print(f"  fail_reason: {data.get('fail_reason')}")
            break
        await asyncio.sleep(3)

    print("\nDone. Open the TikTok app -> inbox notification to finish and post.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
