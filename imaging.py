"""Image preprocessing, EXIF sanitization, resizing, and hashing for KhataScan.

Source of Truth: spec.md §8.2
Privacy by Design: Removes EXIF/GPS metadata and normalizes images for Gemini vision.
"""

import hashlib
import io
from typing import Tuple
from PIL import Image, ImageOps

from config import (
    JPEG_QUALITY,
    MAX_IMAGE_SIDE_PX,
    MAX_UPLOAD_MB,
    MIN_IMAGE_SIDE_PX,
)


class ImageTooSmall(ValueError):
    """Raised when uploaded image resolution is below the minimum required for OCR."""
    pass


class ImageTooLarge(ValueError):
    """Raised when uploaded image file size exceeds the allowed threshold."""
    pass


def sha256_hex(data: bytes) -> str:
    """Compute SHA-256 hex digest of raw or processed bytes."""
    return hashlib.sha256(data).hexdigest()


def preprocess(raw: bytes) -> bytes:
    """Preprocess raw uploaded image bytes.

    1. Checks max file size (MAX_UPLOAD_MB).
    2. Applies EXIF orientation transpose.
    3. Rejects image if short side < MIN_IMAGE_SIDE_PX (raises ImageTooSmall).
    4. Downscales if long side > MAX_IMAGE_SIDE_PX (preserves aspect ratio).
    5. Converts to RGB.
    6. Re-encodes as JPEG (strips GPS/EXIF metadata).

    Returns:
        Sanitized JPEG bytes.
    """
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise ImageTooLarge(
            f"Uploaded file exceeds {MAX_UPLOAD_MB}MB limit."
        )

    try:
        img = Image.open(io.BytesIO(raw))
    except Exception as e:
        raise ValueError(f"Invalid image format: {e}") from e

    # Correct orientation based on EXIF
    img = ImageOps.exif_transpose(img)

    width, height = img.size
    short_side = min(width, height)
    if short_side < MIN_IMAGE_SIDE_PX:
        raise ImageTooSmall(
            f"Image resolution too low ({width}x{height}px). "
            f"Shortest side must be at least {MIN_IMAGE_SIDE_PX}px for legible text."
        )

    # Downscale if long side exceeds maximum
    long_side = max(width, height)
    if long_side > MAX_IMAGE_SIDE_PX:
        scale_factor = MAX_IMAGE_SIDE_PX / float(long_side)
        new_width = max(1, int(round(width * scale_factor)))
        new_height = max(1, int(round(height * scale_factor)))
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Convert to standard RGB (strips alpha channels / CMYK)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Re-encode to clean JPEG without EXIF metadata
    out_buf = io.BytesIO()
    img.save(out_buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out_buf.getvalue()
