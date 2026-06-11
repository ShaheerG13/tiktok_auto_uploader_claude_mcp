"""Tests for the R2 uploader using moto's S3 mock (R2 is S3-compatible)."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from tiktok_slideshow_mcp.config import Settings
from tiktok_slideshow_mcp.storage import R2Uploader, StorageError

BUCKET = "tiktok-slideshows"
PUBLIC_BASE = "https://tt-media.example.com"


def _settings() -> Settings:
    return Settings(
        R2_ACCOUNT_ID="acct",
        R2_ACCESS_KEY_ID="key",
        R2_SECRET_ACCESS_KEY="secret",
        R2_BUCKET=BUCKET,
        R2_PUBLIC_BASE_URL=PUBLIC_BASE,
    )


@pytest.fixture
def uploader():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield R2Uploader(settings=_settings(), client=client), client


def _write_img(tmp_path, name, data=b"\xff\xd8\xff\xe0fake"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_upload_slideshow_preserves_order_and_returns_public_urls(uploader, tmp_path):
    up, client = uploader
    imgs = [_write_img(tmp_path, f"slide{i}.jpg") for i in range(3)]

    urls = up.upload_slideshow(imgs)

    assert len(urls) == 3
    assert all(u.startswith(PUBLIC_BASE + "/slideshows/") for u in urls)
    # Index suffix encodes order.
    assert urls[0].endswith("/0.jpg")
    assert urls[2].endswith("/2.jpg")
    # All share one slideshow prefix.
    prefixes = {u.rsplit("/", 1)[0] for u in urls}
    assert len(prefixes) == 1
    # Objects actually landed in the bucket.
    listed = client.list_objects_v2(Bucket=BUCKET)
    assert listed["KeyCount"] == 3


def test_upload_rejects_unsupported_extension(uploader, tmp_path):
    up, _ = uploader
    bad = _write_img(tmp_path, "slide.gif")
    with pytest.raises(StorageError, match="Unsupported image type"):
        up.upload_slideshow([bad])


def test_upload_missing_file_raises(uploader, tmp_path):
    up, _ = uploader
    with pytest.raises(StorageError, match="not found"):
        up.upload_slideshow([tmp_path / "missing.jpg"])


def test_content_type_inferred(uploader, tmp_path):
    up, client = uploader
    img = _write_img(tmp_path, "slide.png")
    up.upload_slideshow([img])
    obj_key = client.list_objects_v2(Bucket=BUCKET)["Contents"][0]["Key"]
    head = client.head_object(Bucket=BUCKET, Key=obj_key)
    assert head["ContentType"] == "image/png"
