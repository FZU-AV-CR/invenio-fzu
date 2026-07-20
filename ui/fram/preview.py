from io import BytesIO

import numpy as np
from astropy.io import fits
from astropy.visualization import PercentileInterval, AsinhStretch, ImageNormalize
from PIL import Image


def render_fits_preview(filepath):
    """Render the first image HDU of a FITS file as JPEG bytes."""

    with fits.open(filepath, memmap=True) as hdul:
        data = None
        for hdu in hdul:
            if getattr(hdu, "data", None) is not None:
                data = hdu.data
                break

    if data is None:
        raise ValueError("No image HDU found.")

    # Reduce higher-dimensional images
    while data.ndim > 2:
        data = data[0]

    data = np.asarray(data, dtype=np.float32)

    norm = ImageNormalize(
        data,
        interval=PercentileInterval(99.5),
        stretch=AsinhStretch(),
    )

    img = np.clip(norm(data), 0, 1)
    img = (img * 255).astype(np.uint8)

    image = Image.fromarray(img)

    output = BytesIO()
    image.save(output, format="JPEG", quality=90)

    return output.getvalue()
