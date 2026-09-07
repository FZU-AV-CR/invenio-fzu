import React from "react";
import ReactDOM from "react-dom";
import FitsPreviewToolbar from "./FitsPreviewToolbar";

const root = document.getElementById("fits-preview-toolbar-root");
if (root) {
  ReactDOM.render(
    <FitsPreviewToolbar previewUrl={root.dataset.previewUrl} />,
    root
  );
}
