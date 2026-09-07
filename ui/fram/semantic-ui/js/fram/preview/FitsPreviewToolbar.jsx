import React, { useState, useCallback, useMemo, useEffect } from "react";
import PropTypes from "prop-types";
import { Form, Checkbox } from "semantic-ui-react";
import { i18next } from "@translations/i18next";

/**
 * Interactive Stretch/Scale/Zoom/Grid toolbar for the FRAM FITS image
 * preview, replicating the real fram.fzu.cz archive viewer's toolbar
 * (see docs/FITS_DYNAMIC_VIEWER_HANDOFF.md for the full comparison --
 * option values/semantics here are taken directly from that project's
 * own `archive/static/image_overlay.js`, not guessed).
 *
 * All rendering stays server-side: this component only builds the
 * `<img>` src query string (stretch/scale/zoom/dx/dy/grid) and swaps it,
 * exactly like the real archive's `update_image_get_params()` helper.
 * Clicking a quadrant of the image while zoomed in pans in that
 * direction (mirrors `update_image_pos()`).
 */
const STRETCH_OPTIONS = [
  "linear",
  "asinh",
  "log",
  "sqrt",
  "sinh",
  "power",
  "histeq",
];

const SCALE_OPTIONS = ["90", "95", "99", "99.5", "99.9", "99.95", "99.995", "100"];

const ZOOM_OPTIONS = ["1", "2", "4", "8", "16", "32"];

const toOption = (value, label) => ({ key: value, value, text: label ?? value });

const FitsPreviewToolbar = ({ previewUrl }) => {
  const [stretch, setStretch] = useState("asinh");
  const [scale, setScale] = useState("99.5");
  const [zoom, setZoom] = useState("1");
  const [grid, setGrid] = useState(false);
  const [pan, setPan] = useState({ dx: 0, dy: 0 });
  const [loading, setLoading] = useState(false);

  const src = useMemo(() => {
    const url = new URL(previewUrl, window.location.href);
    url.searchParams.set("stretch", stretch);
    url.searchParams.set("scale", scale);
    url.searchParams.set("zoom", zoom);
    url.searchParams.set("grid", grid ? "1" : "0");
    if (zoom !== "1") {
      url.searchParams.set("dx", String(pan.dx));
      url.searchParams.set("dy", String(pan.dy));
    }
    return url.href;
  }, [previewUrl, stretch, scale, zoom, grid, pan]);

  useEffect(() => {
    setLoading(true);
  }, [src]);

  const handleZoomChange = useCallback((_e, { value }) => {
    setZoom(value);
    if (value === "1") {
      setPan({ dx: 0, dy: 0 });
    }
  }, []);

  const handleImageClick = useCallback(
    (event) => {
      const zoomNum = Number(zoom);
      if (zoomNum <= 1) return;

      const rect = event.currentTarget.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width;
      const y = (event.clientY - rect.top) / rect.height;

      const stepX = x > 0.75 ? 1 / zoomNum : x < 0.25 ? -1 / zoomNum : 0;
      const stepY = y < 0.25 ? 1 / zoomNum : y > 0.75 ? -1 / zoomNum : 0;

      if (stepX !== 0 || stepY !== 0) {
        setPan((prev) => ({ dx: prev.dx + stepX, dy: prev.dy + stepY }));
      }
    },
    [zoom]
  );

  return (
    <div className="fits-preview-toolbar-container">
      <Form size="small" className="fits-preview-toolbar rel-mb-1">
        <Form.Group inline>
          <Form.Select
            label={i18next.t("Stretch")}
            options={STRETCH_OPTIONS.map((v) => toOption(v))}
            value={stretch}
            onChange={(_e, { value }) => setStretch(value)}
          />
          <Form.Select
            label={i18next.t("Scale")}
            options={SCALE_OPTIONS.map((v) => toOption(v, `${v}%`))}
            value={scale}
            onChange={(_e, { value }) => setScale(value)}
          />
          <Form.Select
            label={i18next.t("Zoom")}
            options={ZOOM_OPTIONS.map((v) => toOption(v, `x${v}`))}
            value={zoom}
            onChange={handleZoomChange}
          />
          <Form.Field>
            <Checkbox
              label={i18next.t("Grid")}
              checked={grid}
              onChange={(_e, { checked }) => setGrid(checked)}
            />
          </Form.Field>
        </Form.Group>
      </Form>
      <img
        className={`ui fluid image fits-preview-image${loading ? " fits-preview-loading" : ""}`}
        src={src}
        alt={i18next.t("FITS image preview")}
        onLoad={() => setLoading(false)}
        onClick={handleImageClick}
        style={{ cursor: Number(zoom) > 1 ? "crosshair" : "default" }}
      />
    </div>
  );
};

FitsPreviewToolbar.propTypes = {
  previewUrl: PropTypes.string.isRequired,
};

export default FitsPreviewToolbar;
