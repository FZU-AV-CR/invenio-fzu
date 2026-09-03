"""Standalone tests for ui/fram/preview.py's pure FITS-to-JPEG rendering logic.

No Flask/Invenio app context needed -- render_fits_preview() is a pure
function (FITS bytes in, JPEG bytes out), so these tests exercise it
directly against the bundled sample FITS file, matching the pattern
used by docs/FITS_IMAGE_PREVIEW.md's own "easy to unit test standalone"
design rationale.

Run with: .venv/bin/python -m pytest tests/test_fits_preview.py -v
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from ui.fram.preview import (
    DEFAULT_SCALE,
    DEFAULT_STRETCH,
    DEFAULT_ZOOM,
    SCALE_QMAX_PERCENTILES,
    STRETCH_FUNCTIONS,
    ZOOM_LEVELS,
    render_fits_preview,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_FITS = ROOT / "sample_data" / "Fram" / "20260304093525-219-RA.fits"


@pytest.fixture()
def sample_fits_bytes() -> bytes:
    return SAMPLE_FITS.read_bytes()


def _render(sample_fits_bytes: bytes, **kwargs) -> Image.Image:
    jpeg_bytes = render_fits_preview(BytesIO(sample_fits_bytes), **kwargs)
    return Image.open(BytesIO(jpeg_bytes))


def test_default_render_produces_valid_jpeg(sample_fits_bytes):
    image = _render(sample_fits_bytes)
    assert image.format == "JPEG"
    assert image.size[0] > 0
    assert image.size[1] > 0


@pytest.mark.parametrize("stretch", sorted(STRETCH_FUNCTIONS))
def test_all_stretch_options_render(sample_fits_bytes, stretch):
    image = _render(sample_fits_bytes, stretch=stretch)
    assert image.format == "JPEG"


@pytest.mark.parametrize("scale", sorted(SCALE_QMAX_PERCENTILES))
def test_all_scale_options_render(sample_fits_bytes, scale):
    image = _render(sample_fits_bytes, scale=scale)
    assert image.format == "JPEG"


def test_unknown_stretch_falls_back_to_default(sample_fits_bytes):
    fallback = render_fits_preview(BytesIO(sample_fits_bytes), stretch=DEFAULT_STRETCH)
    unknown = render_fits_preview(BytesIO(sample_fits_bytes), stretch="not-a-real-stretch")
    assert unknown == fallback


def test_unknown_scale_falls_back_to_default(sample_fits_bytes):
    fallback = render_fits_preview(BytesIO(sample_fits_bytes), scale=DEFAULT_SCALE)
    unknown = render_fits_preview(BytesIO(sample_fits_bytes), scale="not-a-real-scale")
    assert unknown == fallback


def test_unknown_zoom_falls_back_to_default(sample_fits_bytes):
    fallback = render_fits_preview(BytesIO(sample_fits_bytes), zoom=DEFAULT_ZOOM)
    unknown = render_fits_preview(BytesIO(sample_fits_bytes), zoom="999")
    assert unknown == fallback


@pytest.mark.parametrize("zoom", sorted(ZOOM_LEVELS, key=int))
def test_zoom_crops_to_smaller_image(sample_fits_bytes, zoom):
    base_image = _render(sample_fits_bytes, zoom="1")
    zoomed_image = _render(sample_fits_bytes, zoom=zoom)

    zoom_level = int(zoom)
    # Cropped-before-encode width should shrink roughly by the zoom factor
    # (encoding doesn't resize, so JPEG output dims == cropped dims here).
    assert zoomed_image.size[0] == pytest.approx(base_image.size[0] / zoom_level, rel=0.05) or zoom_level == 1


def test_zoom_with_pan_differs_from_centered_zoom(sample_fits_bytes):
    centered = render_fits_preview(BytesIO(sample_fits_bytes), zoom="4", dx="0", dy="0")
    panned = render_fits_preview(BytesIO(sample_fits_bytes), zoom="4", dx="0.5", dy="0.5")
    assert centered != panned


def test_grid_overlay_changes_output(sample_fits_bytes):
    without_grid = render_fits_preview(BytesIO(sample_fits_bytes), grid=False)
    with_grid = render_fits_preview(BytesIO(sample_fits_bytes), grid=True)
    assert without_grid != with_grid
