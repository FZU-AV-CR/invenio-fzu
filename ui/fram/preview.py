"""Render a FITS image preview (JPEG) from a FRAM record's data file.

Rendering semantics here are deliberately matched to the real
fram.fzu.cz archive viewer (Django app ``fram-archive``,
``archive/views_images.py``'s ``image_preview``/``image_response``
functions), confirmed against that project's actual source and a
stakeholder email exchange (see ``docs/FITS_DYNAMIC_VIEWER_HANDOFF.md``
for the full comparison) -- not guessed from screenshots:

- ``stretch``: one of ``linear``/``asinh``/``log``/``sqrt``/``sinh``/
  ``power``/``histeq``, applied via astropy's stretch classes (plus a
  manual histogram-equalization implementation for ``histeq``, since
  astropy's own ``HistEqStretch`` only needs the raw data array, not
  matplotlib -- confirmed via direct inspection of the installed
  ``astropy.visualization.stretch`` module).
- ``scale``: the fram.fzu.cz viewer's "Scale" dropdown value, which is
  actually the query parameter ``qmax`` server-side -- an *asymmetric*
  percentile pair ``[0.5, qmax]`` (fixed low percentile, variable high
  percentile), NOT a symmetric ``PercentileInterval``. Values:
  90/95/99/99.5/99.9/99.95/99.995/100.
- ``zoom``/``dx``/``dy``: real server-side pixel crop+pan (not a CSS/JS
  no-op) -- crops a ``width/zoom`` x ``height/zoom`` box centered on the
  image center, shifted by ``dx``/``dy`` (fractions of a quadrant),
  matching fram.fzu.cz's click-to-pan behaviour (see
  ``ui/fram/semantic-ui/js/fram/preview/FitsPreviewToolbar.jsx``).
- ``grid``: a simplified grid overlay drawn directly onto the rendered
  JPEG with Pillow (fram.fzu.cz's real grid switches to an entirely
  different matplotlib/STDPipe rendering pipeline with axes/colorbars --
  deliberately not replicated here to avoid a matplotlib dependency for
  a purely cosmetic overlay; see the handoff doc's "Grid" section).

Only the first HDU that actually contains image data is rendered; higher
dimensional data (e.g. data cubes) are reduced by taking the first plane
until a 2D array remains.
"""

from __future__ import annotations

import logging
from io import BytesIO

import numpy as np
from astropy.io import fits
from astropy.visualization import (
    AsinhStretch,
    LinearStretch,
    LogStretch,
    PowerStretch,
    SinhStretch,
    SqrtStretch,
)
from astropy.visualization.stretch import HistEqStretch
from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

#: Supported ``stretch=`` query values, mapped to astropy stretch classes.
#: ``histeq`` is handled specially in ``_apply_stretch`` below since
#: ``HistEqStretch`` needs the data array itself at construction time
#: (it isn't a stateless function like the others).
STRETCH_FUNCTIONS = {
    "linear": LinearStretch,
    "asinh": AsinhStretch,
    "log": LogStretch,
    "sqrt": SqrtStretch,
    "sinh": SinhStretch,
    "power": PowerStretch,
    "histeq": None,
}
DEFAULT_STRETCH = "asinh"

#: Supported ``scale=`` query values -- these map to the real
#: fram.fzu.cz "Scale" dropdown / ``qmax`` query parameter (the high
#: percentile of the clipping interval; the low percentile is always
#: fixed at ``QMIN_PERCENTILE``, matching the real archive's default).
QMIN_PERCENTILE = 0.5
SCALE_QMAX_PERCENTILES = {
    "90": 90.0,
    "95": 95.0,
    "99": 99.0,
    "99.5": 99.5,
    "99.9": 99.9,
    "99.95": 99.95,
    "99.995": 99.995,
    "100": 100.0,
}
DEFAULT_SCALE = "99.5"

#: Supported ``zoom=`` query values, matching fram.fzu.cz's Zoom dropdown.
ZOOM_LEVELS = {"1", "2", "4", "8", "16", "32"}
DEFAULT_ZOOM = "1"
DEFAULT_PAN = "0"

#: Approximate number of grid lines drawn across each axis when
#: ``grid=1`` is requested (cosmetic only, see module docstring).
GRID_DIVISIONS = 10


def _resolve_stretch_name(stretch: str) -> str:
    if stretch not in STRETCH_FUNCTIONS:
        log.warning("Unsupported FITS preview stretch %r, falling back to %s", stretch, DEFAULT_STRETCH)
        return DEFAULT_STRETCH
    return stretch


def _resolve_qmax(scale: str) -> float:
    qmax = SCALE_QMAX_PERCENTILES.get(scale)
    if qmax is None:
        log.warning("Unsupported FITS preview scale %r, falling back to %s", scale, DEFAULT_SCALE)
        qmax = SCALE_QMAX_PERCENTILES[DEFAULT_SCALE]
    return qmax


def _resolve_zoom(zoom: str) -> int:
    if zoom not in ZOOM_LEVELS:
        log.warning("Unsupported FITS preview zoom %r, falling back to %s", zoom, DEFAULT_ZOOM)
        zoom = DEFAULT_ZOOM
    return int(zoom)


def _resolve_pan(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        log.warning("Unsupported FITS preview pan offset %r, falling back to 0", value)
        return 0.0


def _apply_stretch(stretch_name: str, normalized: np.ndarray) -> np.ndarray:
    """Apply the named stretch to a [0, 1]-normalized array, returning [0, 1] floats."""
    if stretch_name == "histeq":
        # Histogram equalization needs the data itself (not just a fixed
        # function), so it's constructed here rather than looked up in
        # STRETCH_FUNCTIONS. This only needs numpy -- no matplotlib.
        stretch = HistEqStretch(normalized)
    else:
        stretch_cls = STRETCH_FUNCTIONS[stretch_name]
        # PowerStretch requires a positional exponent; use a sane default.
        stretch = stretch_cls(2.0) if stretch_cls is PowerStretch else stretch_cls()
    return np.clip(stretch(normalized), 0, 1)


def _crop_zoom_pan(data: np.ndarray, zoom: int, dx: float, dy: float) -> np.ndarray:
    """Crop ``data`` to a ``1/zoom``-sized box centered on the image center,
    shifted by ``(dx, dy)`` quadrant-fractions, matching fram.fzu.cz's
    click-to-pan behaviour. Out-of-bounds regions are padded with the
    median of the visible crop (avoids a black/zero border when panned
    near an edge). No-op when ``zoom <= 1``.
    """
    if zoom <= 1:
        return data

    height, width = data.shape
    x0 = width / 2 + dx * width / 4
    y0 = height / 2 + dy * height / 4

    half_width = width / (2 * zoom)
    half_height = height / (2 * zoom)

    x1, x2 = int(x0 - half_width), int(x0 + half_width)
    y1, y2 = int(y0 - half_height), int(y0 + half_height)

    target_width = max(x2 - x1, 1)
    target_height = max(y2 - y1, 1)

    src_x1, src_y1 = max(0, x1), max(0, y1)
    src_x2, src_y2 = min(width, x2), min(height, y2)

    if src_x2 <= src_x1 or src_y2 <= src_y1:
        # Panned entirely out of bounds -- fall back to an unshifted crop.
        return data

    visible = data[src_y1:src_y2, src_x1:src_x2]
    padded = np.full((target_height, target_width), np.nanmedian(visible), dtype=data.dtype)

    dst_x1, dst_y1 = src_x1 - x1, src_y1 - y1
    dst_x2, dst_y2 = dst_x1 + (src_x2 - src_x1), dst_y1 + (src_y2 - src_y1)
    padded[dst_y1:dst_y2, dst_x1:dst_x2] = visible

    return padded


def _draw_grid(image: Image.Image) -> Image.Image:
    """Draw a simple evenly-spaced grid overlay onto a rendered preview image."""
    image = image.convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    color = (255, 255, 255)

    for i in range(1, GRID_DIVISIONS):
        x = round(width * i / GRID_DIVISIONS)
        draw.line([(x, 0), (x, height)], fill=color, width=1)
    for i in range(1, GRID_DIVISIONS):
        y = round(height * i / GRID_DIVISIONS)
        draw.line([(0, y), (width, y)], fill=color, width=1)

    return image


def render_fits_preview(
    fileobj,
    stretch: str = DEFAULT_STRETCH,
    scale: str = DEFAULT_SCALE,
    zoom: str = DEFAULT_ZOOM,
    dx: str = DEFAULT_PAN,
    dy: str = DEFAULT_PAN,
    grid: bool = False,
) -> bytes:
    """Render the first image HDU of a FITS file as JPEG bytes.

    :param fileobj: path (str/Path) or a file-like/binary-stream object
        opened for reading the FITS content.
    :param stretch: one of ``STRETCH_FUNCTIONS`` keys; unknown values fall
        back to ``DEFAULT_STRETCH``.
    :param scale: one of ``SCALE_QMAX_PERCENTILES`` keys (the "qmax"
        percentile of the clip interval); unknown values fall back to
        ``DEFAULT_SCALE``.
    :param zoom: one of ``ZOOM_LEVELS``; crops the image to a
        ``1/zoom``-sized box centered on the image (or the pan position
        given by ``dx``/``dy``) before rendering.
    :param dx: horizontal pan offset, as a fraction of a quadrant width
        (matches fram.fzu.cz's click-to-pan semantics). Ignored when
        ``zoom`` resolves to ``1``.
    :param dy: vertical pan offset, same semantics as ``dx``.
    :param grid: when true, draws an evenly-spaced grid overlay on top
        of the rendered image (cosmetic only, see module docstring).
    :raises ValueError: if the FITS file has no image data in any HDU.
    """
    with fits.open(fileobj, memmap=False) as hdul:
        data = None
        for hdu in hdul:
            if getattr(hdu, "data", None) is not None:
                data = hdu.data
                break

    if data is None:
        raise ValueError("No image HDU found.")

    # Reduce higher-dimensional images to a 2D plane.
    while data.ndim > 2:
        data = data[0]

    data = np.asarray(data, dtype=np.float32)

    zoom_level = _resolve_zoom(zoom)
    data = _crop_zoom_pan(data, zoom_level, _resolve_pan(dx), _resolve_pan(dy))

    # Normalize manually (rather than via astropy.visualization.ImageNormalize,
    # which subclasses matplotlib.colors.Normalize and therefore requires
    # matplotlib to be installed -- an unnecessary heavyweight dependency for
    # a server-side JPEG rendering endpoint that never displays a plot).
    finite = data[np.isfinite(data)]
    qmax = _resolve_qmax(scale)
    if finite.size:
        vmin, vmax = np.percentile(finite, [QMIN_PERCENTILE, qmax])
    else:
        vmin, vmax = 0.0, 0.0
    if vmax <= vmin:
        # Degenerate (e.g. flat/constant) image -- avoid division by zero.
        normalized = np.zeros_like(data)
    else:
        normalized = np.clip((data - vmin) / (vmax - vmin), 0, 1)

    stretch_name = _resolve_stretch_name(stretch)
    img = _apply_stretch(stretch_name, normalized)
    img = (img * 255).astype(np.uint8)

    image = Image.fromarray(img)
    if grid:
        image = _draw_grid(image)

    output = BytesIO()
    image.save(output, format="JPEG", quality=90)

    return output.getvalue()

