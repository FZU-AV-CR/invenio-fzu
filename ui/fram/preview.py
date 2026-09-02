"""Render a FITS image preview (JPEG) from a FRAM record's data file.

This module intentionally exposes a small, forward-compatible API surface
(``stretch``/``scale``/``zoom`` parameters) even though only a single fixed
combination is currently implemented. This mirrors the fram.fzu.cz archive
viewer's toolbar (Stretch / Scale / Zoom dropdowns) so that interactive
controls can be added later (see ``ui/fram/views.py``) without breaking the
preview endpoint's query-parameter contract.

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
    PercentileInterval,
    PowerStretch,
    SinhStretch,
    SqrtStretch,
)
from PIL import Image

log = logging.getLogger(__name__)

#: Supported ``stretch=`` query values, mapped to astropy stretch classes.
#: Only "asinh" is used by default today; the others are wired in ahead of
#: time so the UI's Stretch dropdown (linear/asinh/log/sqrt/sinh/power) can
#: be implemented later by simply allowing the query parameter through.
STRETCH_FUNCTIONS = {
    "linear": LinearStretch,
    "asinh": AsinhStretch,
    "log": LogStretch,
    "sqrt": SqrtStretch,
    "sinh": SinhStretch,
    "power": PowerStretch,
}
DEFAULT_STRETCH = "asinh"

#: Supported ``scale=`` query values: percentile interval used to clip the
#: pixel value range before stretching.
SCALE_PERCENTILES = {
    "99.5": 99.5,
    "99.9": 99.9,
    "99": 99.0,
    "95": 95.0,
}
DEFAULT_SCALE = "99.5"

#: Supported ``zoom=`` query values. Only "1" (no resampling) is currently
#: implemented; the others are reserved for a future zoomable viewer.
ZOOM_LEVELS = {"1", "2", "4", "8", "16", "32"}
DEFAULT_ZOOM = "1"


def _resolve_stretch(stretch: str):
    stretch_cls = STRETCH_FUNCTIONS.get(stretch)
    if stretch_cls is None:
        log.warning("Unsupported FITS preview stretch %r, falling back to %s", stretch, DEFAULT_STRETCH)
        stretch_cls = STRETCH_FUNCTIONS[DEFAULT_STRETCH]
    # PowerStretch requires a positional exponent; use a sane default.
    if stretch_cls is PowerStretch:
        return stretch_cls(2.0)
    return stretch_cls()


def _resolve_scale(scale: str) -> float:
    percentile = SCALE_PERCENTILES.get(scale)
    if percentile is None:
        log.warning("Unsupported FITS preview scale %r, falling back to %s", scale, DEFAULT_SCALE)
        percentile = SCALE_PERCENTILES[DEFAULT_SCALE]
    return percentile


def render_fits_preview(
    fileobj,
    stretch: str = DEFAULT_STRETCH,
    scale: str = DEFAULT_SCALE,
    zoom: str = DEFAULT_ZOOM,  # noqa: ARG001 - reserved for future zoomable viewer
) -> bytes:
    """Render the first image HDU of a FITS file as JPEG bytes.

    :param fileobj: path (str/Path) or a file-like/binary-stream object
        opened for reading the FITS content.
    :param stretch: one of ``STRETCH_FUNCTIONS`` keys; unknown values fall
        back to ``DEFAULT_STRETCH``.
    :param scale: one of ``SCALE_PERCENTILES`` keys; unknown values fall
        back to ``DEFAULT_SCALE``.
    :param zoom: reserved for future use, currently ignored.
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

    # Normalize manually (rather than via astropy.visualization.ImageNormalize,
    # which subclasses matplotlib.colors.Normalize and therefore requires
    # matplotlib to be installed -- an unnecessary heavyweight dependency for
    # a server-side JPEG rendering endpoint that never displays a plot).
    interval = PercentileInterval(_resolve_scale(scale))
    vmin, vmax = interval.get_limits(data)
    if vmax <= vmin:
        # Degenerate (e.g. flat/constant) image -- avoid division by zero.
        normalized = np.zeros_like(data)
    else:
        normalized = np.clip((data - vmin) / (vmax - vmin), 0, 1)

    img = np.clip(_resolve_stretch(stretch)(normalized), 0, 1)
    img = (img * 255).astype(np.uint8)

    image = Image.fromarray(img)

    output = BytesIO()
    image.save(output, format="JPEG", quality=90)

    return output.getvalue()

