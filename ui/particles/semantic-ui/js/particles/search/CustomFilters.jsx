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
 * filters stacked (same pattern as the FRAM/SiPM/Atlas ITk models'
 * CustomFilters.jsx).
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
 * Collision-energy range filter (min/max input, "overlap" semantics --
 * see EnergyRangeOverlapFacet's docstring in models/particles/facets.py).
 * Sends a single "min..max" string value (either bound may be omitted),
 * the same range-string convention used by FRAM's RangeQueryFacet-backed
 * filters (exposure, altitude, azimuth, observation_night).
 */
const EnergyFilterComponent = ({
  currentQueryState,
  updateQueryState,
  active,
  onToggle,
}) => {
  const filterKey = "metadata.collision_information.energy_range";
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");

  const apply = () => {
    const minNum = min === "" ? null : parseFloat(min);
    const maxNum = max === "" ? null : parseFloat(max);
    if (
      (minNum !== null && Number.isNaN(minNum)) ||
      (maxNum !== null && Number.isNaN(maxNum)) ||
      (minNum === null && maxNum === null)
    ) {
      return; // nothing valid to send
    }
    updateQueryState({
      ...currentQueryState,
      filters: withFilter(
        currentQueryState.filters,
        filterKey,
        `${minNum !== null ? minNum : ""}..${maxNum !== null ? maxNum : ""}`
      ),
    });
  };

  const clear = () => {
    setMin("");
    setMax("");
    updateQueryState({
      ...currentQueryState,
      filters: withoutFilter(currentQueryState.filters, filterKey),
    });
  };

  return (
    <FilterPanel
      label={i18next.t("Collision energy (TeV)")}
      active={active}
      onToggle={onToggle}
    >
      <Form.Input
        label={i18next.t("Min")}
        type="number"
        value={min}
        onChange={(e) => setMin(e.target.value)}
        placeholder="e.g. 7"
      />
      <Form.Input
        label={i18next.t("Max")}
        type="number"
        value={max}
        onChange={(e) => setMax(e.target.value)}
        placeholder="e.g. 13"
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

EnergyFilterComponent.propTypes = {
  currentQueryState: PropTypes.object.isRequired,
  updateQueryState: PropTypes.func.isRequired,
  active: PropTypes.bool.isRequired,
  onToggle: PropTypes.func.isRequired,
};

const EnergyFilter = withState(EnergyFilterComponent);

/**
 * Title partial-match filter (single text input, case-insensitive
 * substring match -- see TextMatchFacet's docstring in
 * models/particles/facets.py). Sends a single plain-string filter
 * value, no special syntax, same convention as FRAM's
 * FilenameFilter/TitleFilter.
 */
const TitleFilterComponent = ({
  currentQueryState,
  updateQueryState,
  active,
  onToggle,
}) => {
  const filterKey = "metadata.title";
  const [value, setValue] = useState("");

  const apply = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    updateQueryState({
      ...currentQueryState,
      filters: withFilter(currentQueryState.filters, filterKey, trimmed),
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
    <FilterPanel
      label={i18next.t("Title")}
      active={active}
      onToggle={onToggle}
    >
      <Form.Input
        label={i18next.t("Title contains")}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={i18next.t("e.g. calibration")}
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

TitleFilterComponent.propTypes = {
  currentQueryState: PropTypes.object.isRequired,
  updateQueryState: PropTypes.func.isRequired,
  active: PropTypes.bool.isRequired,
  onToggle: PropTypes.func.isRequired,
};

const TitleFilter = withState(TitleFilterComponent);

/**
 * Number-of-events range filter (min/max input -- see RangeQueryFacet's
 * docstring in models/particles/facets.py, registered on
 * metadata.number_of_events via a `facet-def` in metadata.yaml). Sends
 * a single "min..max" string value (either bound may be omitted), same
 * range-string convention used by EnergyFilter above and FRAM's
 * RangeQueryFacet-backed filters.
 */
const NumberOfEventsFilterComponent = ({
  currentQueryState,
  updateQueryState,
  active,
  onToggle,
}) => {
  const filterKey = "metadata.number_of_events";
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");

  const apply = () => {
    const minNum = min === "" ? null : parseFloat(min);
    const maxNum = max === "" ? null : parseFloat(max);
    if (
      (minNum !== null && Number.isNaN(minNum)) ||
      (maxNum !== null && Number.isNaN(maxNum)) ||
      (minNum === null && maxNum === null)
    ) {
      return; // nothing valid to send
    }
    updateQueryState({
      ...currentQueryState,
      filters: withFilter(
        currentQueryState.filters,
        filterKey,
        `${minNum !== null ? minNum : ""}..${maxNum !== null ? maxNum : ""}`
      ),
    });
  };

  const clear = () => {
    setMin("");
    setMax("");
    updateQueryState({
      ...currentQueryState,
      filters: withoutFilter(currentQueryState.filters, filterKey),
    });
  };

  return (
    <FilterPanel
      label={i18next.t("Number of events")}
      active={active}
      onToggle={onToggle}
    >
      <Form.Input
        label={i18next.t("Min")}
        type="number"
        value={min}
        onChange={(e) => setMin(e.target.value)}
        placeholder="e.g. 1000"
      />
      <Form.Input
        label={i18next.t("Max")}
        type="number"
        value={max}
        onChange={(e) => setMax(e.target.value)}
        placeholder="e.g. 5000"
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

NumberOfEventsFilterComponent.propTypes = {
  currentQueryState: PropTypes.object.isRequired,
  updateQueryState: PropTypes.func.isRequired,
  active: PropTypes.bool.isRequired,
  onToggle: PropTypes.func.isRequired,
};

const NumberOfEventsFilter = withState(NumberOfEventsFilterComponent);

/**
 * "Created" date range filter (min/max native date inputs -- see
 * DatesTypeRangeFacet's docstring in models/particles/facets.py,
 * registered under the virtual key "metadata.dates.created_range").
 * Native <input type="date"> produces a "YYYY-MM-DD" value directly,
 * matching the format OpenSearch's `date` field type expects in a
 * `range` query -- no client-side reformatting needed. Sends a single
 * "min..max" string value (either bound may be omitted).
 */
const CreatedDateFilterComponent = ({
  currentQueryState,
  updateQueryState,
  active,
  onToggle,
}) => {
  const filterKey = "metadata.dates.created_range";
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");

  const apply = () => {
    if (!min && !max) return; // nothing valid to send
    updateQueryState({
      ...currentQueryState,
      filters: withFilter(currentQueryState.filters, filterKey, `${min}..${max}`),
    });
  };

  const clear = () => {
    setMin("");
    setMax("");
    updateQueryState({
      ...currentQueryState,
      filters: withoutFilter(currentQueryState.filters, filterKey),
    });
  };

  return (
    <FilterPanel
      label={i18next.t("Created date")}
      active={active}
      onToggle={onToggle}
    >
      <Form.Input
        label={i18next.t("From")}
        type="date"
        value={min}
        onChange={(e) => setMin(e.target.value)}
      />
      <Form.Input
        label={i18next.t("To")}
        type="date"
        value={max}
        onChange={(e) => setMax(e.target.value)}
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

CreatedDateFilterComponent.propTypes = {
  currentQueryState: PropTypes.object.isRequired,
  updateQueryState: PropTypes.func.isRequired,
  active: PropTypes.bool.isRequired,
  onToggle: PropTypes.func.isRequired,
};

const CreatedDateFilter = withState(CreatedDateFilterComponent);

/**
 * Definition of every custom filter panel, in display order.
 */
const FILTER_PANELS = [
  { key: "title", Component: TitleFilter },
  { key: "energy_range", Component: EnergyFilter },
  { key: "number_of_events", Component: NumberOfEventsFilter },
  { key: "created_date", Component: CreatedDateFilter },
];

/**
 * Combined custom filters block. Standard checkbox facets (title,
 * experiment, category, dataset_type, collision_information.type,
 * file_types -- see AddFacetGroup in models/particles/model.py) are
 * rendered first via <SearchAppFacets>, followed by the custom
 * input-based filters below, each collapsed into an accordion panel
 * (see FilterPanel above).
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
