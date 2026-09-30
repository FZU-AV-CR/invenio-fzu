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

import numpy as np
import pytest
from astropy.io import fits
from PIL import Image

from ui.fram.preview import (
    CMAP_STOPS,
    DEFAULT_CMAP,
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


def test_default_render_is_colored_not_grayscale(sample_fits_bytes):
    """Default cmap is Blues_r, so the output must not be flat grayscale.

    A grayscale image would have R == G == B for every pixel; Blues_r
    maps low/high values to distinctly-tinted blue shades, so at least
    some pixels must have unequal channels.
    """
    image = _render(sample_fits_bytes).convert("RGB")
    pixels = np.asarray(image)
    not_gray = ~np.all(pixels[..., 0:1] == pixels, axis=-1)
    assert not_gray.any(), "expected at least some non-gray (colored) pixels with the default Blues_r cmap"


@pytest.mark.parametrize("cmap", sorted(CMAP_STOPS))
def test_all_cmap_options_render(sample_fits_bytes, cmap):
    image = _render(sample_fits_bytes, cmap=cmap)
    assert image.format == "JPEG"
    assert image.mode == "RGB"


def test_unknown_cmap_falls_back_to_default(sample_fits_bytes):
    fallback = render_fits_preview(BytesIO(sample_fits_bytes), cmap=DEFAULT_CMAP)
    unknown = render_fits_preview(BytesIO(sample_fits_bytes), cmap="not-a-real-cmap")
    assert unknown == fallback


def test_different_cmaps_produce_different_output(sample_fits_bytes):
    blues = render_fits_preview(BytesIO(sample_fits_bytes), cmap="Blues_r")
    greys = render_fits_preview(BytesIO(sample_fits_bytes), cmap="Greys_r")
    assert blues != greys


def test_blues_r_is_dark_at_low_values_and_light_at_high_values(sample_fits_bytes):
    """Sanity-check Blues_r control points: low normalized values should
    render as dark navy, high normalized values as near-white -- this is
    the "_r" (reversed) semantics matching matplotlib's own convention
    and the real fram.fzu.cz archive's default appearance.
    """
    from ui.fram.preview import _apply_colormap

    normalized = np.array([[0.0, 1.0]])
    rgb = _apply_colormap(normalized, "Blues_r")

    dark_pixel = rgb[0, 0]
    light_pixel = rgb[0, 1]

    assert dark_pixel.sum() < light_pixel.sum()
    # The real archive's darkest Blues_r stop is (8, 48, 107) and the
    # lightest is (247, 251, 255) -- confirm we land on/near those ends.
    assert tuple(int(v) for v in dark_pixel) == (8, 48, 107)
    assert tuple(int(v) for v in light_pixel) == (247, 251, 255)


def test_output_is_vertically_flipped_relative_to_raw_fits_data(tmp_path):
    """FITS row 0 is conventionally the bottom of the sky image, but
    PIL/JPEG assume row 0 is the top -- render_fits_preview() must flip
    vertically (matching the real archive's cv2.flip(data, 0)) so a
    bright pixel placed in the FITS array's *last* row ends up rendered
    near the *top* of the output JPEG, not the bottom.
    """
    height, width = 40, 40
    data = np.zeros((height, width), dtype=np.float32)
    # Bright square in the FITS array's last rows (conventionally the
    # "top" of the sky once correctly oriented).
    data[height - 5 :, :] = 1000.0

    fits_path = tmp_path / "synthetic.fits"
    fits.PrimaryHDU(data=data).writeto(fits_path)

    image = Image.open(BytesIO(render_fits_preview(str(fits_path), stretch="linear"))).convert("L")
    pixels = np.asarray(image)

    top_band_brightness = pixels[: height // 4, :].mean()
    bottom_band_brightness = pixels[-height // 4 :, :].mean()

    # After the flip, the bright FITS rows (originally at the bottom of
    # the array) must appear at the top of the rendered image.
    assert top_band_brightness > bottom_band_brightness
