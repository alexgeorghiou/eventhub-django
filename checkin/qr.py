"""QR code rendering.

segno is pure Python (no Pillow dependency) and writes PNG and SVG directly.
"""

from __future__ import annotations

import io

import segno


def qr_png(data: str, *, scale: int = 8) -> bytes:
    buffer = io.BytesIO()
    segno.make(data, error="m", micro=False).save(buffer, kind="png", scale=scale, border=2)
    return buffer.getvalue()


def qr_svg_data_uri(data: str, *, scale: int = 4) -> str:
    """Inline-able SVG, handy for emails and pages that should not hit the server again."""
    return segno.make(data, error="m", micro=False).svg_data_uri(scale=scale, border=2)
