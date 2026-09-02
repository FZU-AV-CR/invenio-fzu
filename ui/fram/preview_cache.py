"""Sharded, checksum-keyed disk cache for rendered FITS preview JPEGs.

Rendering a FITS preview (opening a ~30MB file, computing a percentile
interval + asinh stretch, encoding a JPEG) is relatively expensive, so
rendered images are cached on disk under::

    <instance_path>/fits_previews/<xx>/<yy>/<cache_key>.jpg

where ``<xx>``/``<yy>`` are the first four hex characters of the cache key
(sharding avoids very large single directories). The cache key is derived
from the source file's checksum plus the rendering parameters
(stretch/scale/zoom), so a re-uploaded file (different checksum) or a
different rendering request never collides with a stale cache entry.

Writes are atomic (render to a temporary file in the same shard directory,
then ``os.replace`` into place) so concurrent requests for the same not-yet
-cached image never see a partially written file.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Callable

from flask import current_app

log = logging.getLogger(__name__)

CACHE_DIR_NAME = "fits_previews"


def _cache_root() -> Path:
    """Return the root directory for the preview cache, creating it if needed."""
    root = Path(current_app.instance_path) / CACHE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_key(checksum: str, stretch: str, scale: str, zoom: str) -> str:
    """Compute a stable cache key from the file checksum and render params."""
    payload = f"{checksum}:{stretch}:{scale}:{zoom}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cache_path(cache_key: str) -> Path:
    """Return the sharded on-disk path for a given cache key."""
    root = _cache_root()
    shard_dir = root / cache_key[:2] / cache_key[2:4]
    shard_dir.mkdir(parents=True, exist_ok=True)
    return shard_dir / f"{cache_key}.jpg"


def get_or_render_preview(
    checksum: str,
    stretch: str,
    scale: str,
    zoom: str,
    render_fn: Callable[[], bytes],
) -> Path:
    """Return the cached preview JPEG path, rendering and caching it first if needed.

    :param checksum: checksum of the source FITS file (from file metadata),
        used together with the render parameters to key the cache.
    :param stretch: ``stretch=`` render parameter, see ``preview.py``.
    :param scale: ``scale=`` render parameter, see ``preview.py``.
    :param zoom: ``zoom=`` render parameter, see ``preview.py``.
    :param render_fn: zero-argument callable returning the rendered JPEG
        bytes; only invoked on a cache miss.
    :return: path to the cached JPEG file on disk.
    """
    cache_key = _cache_key(checksum, stretch, scale, zoom)
    cache_path = _cache_path(cache_key)

    if cache_path.exists():
        return cache_path

    jpeg_bytes = render_fn()

    # Atomic write: render into a temp file in the same directory, then
    # rename into place so concurrent readers never see a partial file.
    fd, tmp_name = tempfile.mkstemp(dir=cache_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(jpeg_bytes)
        os.replace(tmp_name, cache_path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise

    return cache_path
