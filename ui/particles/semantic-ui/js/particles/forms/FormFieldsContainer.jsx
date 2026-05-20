// old form
import * as React from "react";
import {
  useFormConfig,
  FormikStateLogger,
  TextField,
} from "@js/oarepo_ui/forms";
import { AccordionField } from "react-invenio-forms";
import { i18next } from "@translations/i18next";
import { UppyUploader } from "@js/invenio_rdm_records";
import { connect } from "react-redux";
import PropTypes from "prop-types";

const FormFieldsContainerComponent = ({ record }) => {
  const formConfig = useFormConfig();
  const { filesLocked } = formConfig;
  return (
    <React.Fragment>
      <AccordionField
        includesPaths={["metadata.title"]}
        active
        label={i18next.t("Basic information")}
      >
        <TextField fieldPath="metadata.title" />
      </AccordionField>
      <AccordionField
        includesPaths={["files.enabled"]}
        active
        label={
          <label htmlFor="files.enabled">{i18next.t("Files upload")}</label>
        }
        data-testid="filesupload-button"
      >
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
      </AccordionField>
      {process.env.NODE_ENV === "development" && <FormikStateLogger />}
    </React.Fragment>
  );
};

FormFieldsContainerComponent.propTypes = {
  record: PropTypes.object.isRequired,
};

const mapStateToProps = (state) => {
  return {
    record: state.deposit.record,
  };
};

export default connect(mapStateToProps)(FormFieldsContainerComponent);

//
// new form
// import { DepositFormApp, parseFormAppConfig } from "@js/oarepo_ui/forms";
// import React from "react";
// import ReactDOM from "react-dom";
// import { EDTFSingleDatePicker } from "@js/oarepo_ui/forms";
// import { parametrize } from "react-overridable";
// import {
//   CCMMDepositRecordSerializer,
//   CCMMSections,
// } from "@js/ccmm_invenio/forms";

// const { rootEl, config, ...rest } = parseFormAppConfig();
// const recordSerializer = new CCMMDepositRecordSerializer(
//   config.default_locale,
//   config.custom_fields.vocabularies,
// );

// const parametrizeEDTFSingleDatePicker = parametrize(EDTFSingleDatePicker, {
//   customInputProps: { width: 16 },
// });

// export const componentOverrides = {
//   "InvenioRdmRecords.DepositForm.DatesField.DateField":
//     parametrizeEDTFSingleDatePicker,
// };

// ReactDOM.render(
//   <DepositFormApp
//     config={config}
//     {...rest}
//     sections={CCMMSections}
//     recordSerializer={recordSerializer}
//     componentOverrides={componentOverrides}
//     useWizardForm
//   />,
//   rootEl,
// );
