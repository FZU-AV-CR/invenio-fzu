import React, { useState } from "react";
import PropTypes from "prop-types";
import { SearchAppFacets } from "@js/oarepo_ui/search";
import { withState } from "react-searchkit";
import { Form, Button, Accordion, Icon } from "semantic-ui-react";
import { i18next } from "@translations/i18next";

/**
 * Shared accordion-panel wrapper for all custom input-based filters below.
 * Collapsed by default, expands on click -- keeps a single narrow sidebar
 * column from overflowing into the results column even with several
 * filters stacked (same pattern as the FRAM model's CustomFilters.jsx).
 *
 * `active`/`onToggle` are owned by the parent <Accordion exclusive={false}>
 * (see CustomFilters at the bottom of this file) so multiple filter panels
 * can be expanded at the same time.
 */
const FilterPanel = ({ label, active, onToggle, children }) => (
  <>
    <Accordion.Title active={active} onClick={onToggle}>
      <Icon name="dropdown" />
      {label}
    </Accordion.Title>
    <Accordion.Content active={active}>
      <Form size="small">{children}</Form>
    </Accordion.Content>
  </>
);

FilterPanel.propTypes = {
  label: PropTypes.string.isRequired,
  active: PropTypes.bool.isRequired,
  onToggle: PropTypes.func.isRequired,
  children: PropTypes.node,
};

/**
 * Helper to replace/remove a single named filter within react-searchkit's
 * `filters` array (an array of [key, value] tuples) while leaving all other
 * active filters untouched.
 */
const withFilter = (filters, key, value) => [
  ...(filters || []).filter((f) => f[0] !== key),
  ...(value != null ? [[key, value]] : []),
];

const withoutFilter = (filters, key) =>
  (filters || []).filter((f) => f[0] !== key);

/**
 * Generic free-text input filter factory, used for high-cardinality
 * array-of-keyword fields (tray_numbers, qr_list) where a checkbox facet
 * bucket list would be unusable (potentially thousands of distinct
 * values), matched via the custom TextMatchFacet registered for these
 * fields (see models/sipm/facets.py).
 */
const makeTextFilter = (filterKey, labelText, placeholderText) => {
  const TextFilterComponent = ({
    currentQueryState,
    updateQueryState,
    active,
    onToggle,
  }) => {
    const [value, setValue] = useState("");

    const apply = () => {
      if (!value) return;
      updateQueryState({
        ...currentQueryState,
        filters: withFilter(currentQueryState.filters, filterKey, value),
      });
    };

    const clear = () => {
      setValue("");
      updateQueryState({
        ...currentQueryState,
        filters: withoutFilter(currentQueryState.filters, filterKey),
      });
    };

    return (
      <FilterPanel label={labelText} active={active} onToggle={onToggle}>
        <Form.Input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholderText}
        />
        <Button.Group size="small" fluid>
          <Button primary onClick={apply} type="button">
            {i18next.t("Search")}
          </Button>
          <Button basic onClick={clear} type="button">
            {i18next.t("Clear")}
          </Button>
        </Button.Group>
      </FilterPanel>
    );
  };

  TextFilterComponent.propTypes = {
    currentQueryState: PropTypes.object.isRequired,
    updateQueryState: PropTypes.func.isRequired,
    active: PropTypes.bool.isRequired,
    onToggle: PropTypes.func.isRequired,
  };

  return withState(TextFilterComponent);
};

const BoxFilter = makeTextFilter(
  "metadata.box",
  i18next.t("Box"),
  i18next.t("e.g. Prg01")
);

const TrayNumbersFilter = makeTextFilter(
  "metadata.tray_numbers",
  i18next.t("Tray numbers"),
  i18next.t("e.g. Tray000030")
);

const QrListFilter = makeTextFilter(
  "metadata.qr_list",
  i18next.t("QR (strip ID)"),
  i18next.t("e.g. 0123456789")
);

/**
 * Definition of every custom filter panel, in display order.
 */
const FILTER_PANELS = [
  { key: "box", Component: BoxFilter },
  { key: "tray_numbers", Component: TrayNumbersFilter },
  { key: "qr_list", Component: QrListFilter },
];

/**
 * Combined custom filters block. Standard checkbox facets (box,
 * requestor, manufacturer, title -- see AddFacetGroup in
 * models/sipm/model.py) are rendered first via <SearchAppFacets>,
 * followed by the custom input-based filters below, each collapsed into
 * an accordion panel (see FilterPanel above).
 */
export const CustomFilters = (props) => {
  const [openPanels, setOpenPanels] = useState({});

  const togglePanel = (key) =>
    setOpenPanels((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <>
      <SearchAppFacets {...props} />
      <div className="custom-filters-wrapper custom-filters-for-model">
        <Accordion exclusive={false} styled fluid className="custom-filters-accordion">
          {FILTER_PANELS.map(({ key, Component }) => (
            <Component
              key={key}
              active={!!openPanels[key]}
              onToggle={() => togglePanel(key)}
            />
          ))}
        </Accordion>
      </div>
    </>
  );
};

CustomFilters.propTypes = SearchAppFacets.propTypes;

export default CustomFilters;
