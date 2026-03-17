import { DepositFormApp, parseFormAppConfig } from "@js/oarepo_ui/forms";
import React from "react";
import ReactDOM from "react-dom";
import { i18next } from "@translations/i18next";
import { TitlesField, UppyUploader } from "@js/invenio_rdm_records";

const { rootEl, config, ...rest } = parseFormAppConfig();

const sections = [
  {
    key: "basic-information",
    label: i18next.t("Basic information"),
    render: ({ record, formConfig }) => {
      const { vocabularies } = formConfig.config;
      return (
        <TitlesField
          options={vocabularies?.titles}
          fieldPath="metadata.title"
          recordUI={record.ui}
          required
        />
      );
    },
    includesPaths: ["metadata.title"],
  },
  {
    key: "files",
    label: i18next.t("Files upload"),
    render: ({ record, formConfig }) => {
      const { filesLocked } = formConfig.config;
      return (
        <UppyUploader
          isDraftRecord={!record.is_published}
          config={formConfig}
          quota={formConfig.quota}
          decimalSizeDisplay={formConfig.decimal_size_display}
          allowEmptyFiles={formConfig.allow_empty_files}
          fileUploadConcurrency={formConfig.file_upload_concurrency}
          showMetadataOnlyToggle={false}
          filesLocked={filesLocked}
        />
      );
    },
    includesPaths: ["files.enabled"],
  },
];

ReactDOM.render(
  <DepositFormApp
    config={config}
    {...rest}
    sections={sections}
    useWizardForm
  />,
  rootEl,
);
