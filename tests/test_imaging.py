"""Unit tests for imaging.py."""

import io
from PIL import Image
import pytest
from imaging import (
    ImageTooLarge,
    ImageTooSmall,
    preprocess,
    sha256_hex,
)


def _make_dummy_image_bytes(width: int, height: int, format: str = "PNG") -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()


def test_tiny_photo_rejected():
    # 400x500 is below MIN_IMAGE_SIDE_PX (600)
    raw = _make_dummy_image_bytes(400, 500)
    with pytest.raises(ImageTooSmall):
        preprocess(raw)


def test_big_photo_downscaled():
    # 3000x2400 is above MAX_IMAGE_SIDE_PX (2000)
    raw = _make_dummy_image_bytes(3000, 2400)
    processed = preprocess(raw)
    out_img = Image.open(io.BytesIO(processed))
    assert max(out_img.size) == 2000
    assert out_img.format == "JPEG"


def test_standard_photo_processed():
    # 800x1200 is within acceptable bounds
    raw = _make_dummy_image_bytes(800, 1200)
    processed = preprocess(raw)
    out_img = Image.open(io.BytesIO(processed))
    assert out_img.size == (800, 1200)
    assert out_img.format == "JPEG"


def test_sha256_hex():
    data = b"khatascan_test_ledger"
    digest = sha256_hex(data)
    assert isinstance(digest, str)
    assert len(digest) == 64
