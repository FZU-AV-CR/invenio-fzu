"""Redis-backed (Invenio-cache) cache for rendered FITS preview JPEGs.

Rendering a FITS preview (opening a ~30MB file, computing a percentile
interval + asinh stretch, encoding a JPEG) is relatively expensive, so
rendered images are cached keyed on the source file's checksum plus the
rendering parameters (stretch/scale/zoom/dx/dy/grid), so a re-uploaded
file (different checksum) or a different rendering request never
collides with a stale cache entry.

This previously used a sharded on-disk cache under
``<instance_path>/fits_previews/<xx>/<yy>/<cache_key>.jpg``. That does
not work in a Kubernetes deployment (e.g. the test1 environment): pods
run with read-only/ephemeral root filesystems and/or no shared/persistent
volume for ``instance_path``, so writes either fail outright or are
silently lost/not shared across replicas. Instead, this now uses
``invenio_cache.current_cache`` (``flask_caching`` under the hood,
Redis-backed by Invenio's own default configuration -- the same Redis
instance already required by InvenioRDM for sessions/rate-limiting, so no
new infrastructure is needed). Cached values are plain JPEG ``bytes``
(pickled by the cache backend), with a bounded TTL so cache memory is
reclaimed automatically rather than growing unbounded like the old disk
cache did.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Callable

from invenio_cache import current_cache

log = logging.getLogger(__name__)

#: Namespacing prefix so preview cache keys can't collide with unrelated
#: values in the shared Invenio cache (sessions, other subsystems, ...).
CACHE_KEY_PREFIX = "fits_preview::"

#: How long a rendered preview stays cached, in seconds. Matches the
#: `Cache-Control: max-age` sent to browsers in `views.py` -- both bound
#: how long a rendered image is considered valid to reuse.
CACHE_TIMEOUT = 24 * 60 * 60  # 24 hours


def _cache_key(checksum: str, stretch: str, scale: str, zoom: str, dx: str, dy: str, grid: str) -> str:
    """Compute a stable cache key from the file checksum and render params."""
    payload = f"{checksum}:{stretch}:{scale}:{zoom}:{dx}:{dy}:{grid}".encode("utf-8")
    return CACHE_KEY_PREFIX + hashlib.sha256(payload).hexdigest()


def get_or_render_preview(
    checksum: str,
    stretch: str,
    scale: str,
    zoom: str,
    render_fn: Callable[[], bytes],
    dx: str = "0",
    dy: str = "0",
    grid: str = "0",
) -> bytes:
    """Return the cached preview JPEG bytes, rendering and caching first if needed.

    :param checksum: checksum of the source FITS file (from file metadata),
        used together with the render parameters to key the cache.
    :param stretch: ``stretch=`` render parameter, see ``preview.py``.
    :param scale: ``scale=`` render parameter, see ``preview.py``.
    :param zoom: ``zoom=`` render parameter, see ``preview.py``.
    :param render_fn: zero-argument callable returning the rendered JPEG
        bytes; only invoked on a cache miss.
    :param dx: ``dx=`` pan parameter, see ``preview.py``.
    :param dy: ``dy=`` pan parameter, see ``preview.py``.
    :param grid: ``grid=`` overlay parameter, see ``preview.py``.
    :return: the rendered JPEG bytes (from cache, or freshly rendered).
    """
    cache_key = _cache_key(checksum, stretch, scale, zoom, dx, dy, grid)

    cached = current_cache.get(cache_key)
    if cached is not None:
        return cached

    jpeg_bytes = render_fn()
    current_cache.set(cache_key, jpeg_bytes, timeout=CACHE_TIMEOUT)

    return jpeg_bytes


def cache_key_for(checksum: str, stretch: str, scale: str, zoom: str, dx: str, dy: str, grid: str) -> str:
    """Public helper to compute the same cache key used internally, for ETags."""
    return _cache_key(checksum, stretch, scale, zoom, dx, dy, grid)
