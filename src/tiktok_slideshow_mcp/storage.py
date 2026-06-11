"""Cloudflare R2 image uploader.

Uploads local image files to an R2 bucket (S3-compatible) and returns public URLs served
from the TikTok-verified custom domain. TikTok's photo post endpoint pulls these URLs.
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig

from .config import Settings, get_settings

# Extensions TikTok accepts for photo posts.
_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
_DEFAULT_CONTENT_TYPE = "application/octet-stream"


class StorageError(RuntimeError):
    pass


class R2Uploader:
    def __init__(self, settings: Settings | None = None, client=None):
        self.settings = settings or get_settings()
        self.settings.require_r2()
        self._client = client or boto3.client(
            "s3",
            endpoint_url=self.settings.r2_endpoint_url,
            aws_access_key_id=self.settings.r2_access_key_id,
            aws_secret_access_key=self.settings.r2_secret_access_key,
            region_name="auto",
            config=BotoConfig(signature_version="s3v4"),
        )

    def _public_url(self, key: str) -> str:
        base = self.settings.r2_public_base_url.rstrip("/")
        return f"{base}/{key}"

    def upload_file(self, local_path: str | Path, key: str) -> str:
        """Upload one file to R2 under `key`, return its public URL."""
        path = Path(local_path)
        if not path.is_file():
            raise StorageError(f"Image file not found: {path}")
        content_type = mimetypes.guess_type(path.name)[0] or _DEFAULT_CONTENT_TYPE
        with path.open("rb") as fh:
            self._client.put_object(
                Bucket=self.settings.r2_bucket,
                Key=key,
                Body=fh,
                ContentType=content_type,
            )
        return self._public_url(key)

    def upload_slideshow(self, image_paths: list[str | Path]) -> list[str]:
        """Upload an ordered set of images under a shared prefix; return public URLs in order.

        Image ordering is preserved (TikTok renders the slideshow in array order).
        """
        if not image_paths:
            raise StorageError("No images supplied.")
        prefix = f"slideshows/{uuid.uuid4().hex}"
        urls: list[str] = []
        for idx, p in enumerate(image_paths):
            path = Path(p)
            ext = path.suffix.lower()
            if ext not in _ALLOWED_EXT:
                raise StorageError(
                    f"Unsupported image type '{ext}' for {path.name}; "
                    f"TikTok photo posts accept {sorted(_ALLOWED_EXT)}."
                )
            key = f"{prefix}/{idx}{ext}"
            urls.append(self.upload_file(path, key))
        return urls
