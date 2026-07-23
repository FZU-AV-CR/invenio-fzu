import React, { useState } from "react";
import PropTypes from "prop-types";
import { SearchAppFacets } from "@js/oarepo_ui/search";
import { withState } from "react-searchkit";
import { Form, Button, Accordion, Icon } from "semantic-ui-react";
import { i18next } from "@translations/i18next";

/**
 * Shared accordion-panel wrapper for all custom input-based filters below.
 * Replaces the previous plain <Segment>+<Header> / 2-column CSS grid
 * layout: each filter is now collapsed by default and expands on click,
 * so 8 filters can be stacked in a single narrow sidebar column without
 * overflowing into the results column (the 2-column grid version
 * previously overflowed at narrower viewport/sidebar widths).
 *
 * `active`/`onToggle` are owned by the parent <Accordion exclusive={false}>
 * (see CustomFilters at the bottom of this file) so multiple filter panels
 * can be expanded at the same time (e.g. Altitude + Azimuth together).
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
 * Sky position cone search: RA (deg), Dec (deg), Radius (deg).
 *
 * On submit, stores a single "cone_search" filter as a JSON string
 * { lat, lon, radius }. RA is remapped to OpenSearch longitude range
 * (-180..180) here so downstream query-building code doesn't have to.
 */
const ConeSearchInputsComponent = ({
  currentQueryState,
  updateQueryState,
  active,
  onToggle,
}) => {
  const [ra, setRa] = useState("");
  const [dec, setDec] = useState("");
  const [radius, setRadius] = useState("");

  const apply = () => {
    const raNum = parseFloat(ra);
    const decNum = parseFloat(dec);
    const radiusNum = parseFloat(radius);
    if (
      Number.isNaN(raNum) ||
      Number.isNaN(decNum) ||
      Number.isNaN(radiusNum)
    ) {
      return;
    }
    const lon = raNum > 180 ? raNum - 360 : raNum;
    updateQueryState({
      ...currentQueryState,
      filters: withFilter(
        currentQueryState.filters,
        "cone_search",
        JSON.stringify({ lat: decNum, lon, radius: radiusNum })
      ),
    });
  };

  const clear = () => {
    setRa("");
    setDec("");
    setRadius("");
    updateQueryState({
      ...currentQueryState,
      filters: withoutFilter(currentQueryState.filters, "cone_search"),
    });
  };

  return (
    <FilterPanel label={i18next.t("Sky position")} active={active} onToggle={onToggle}>
      <Form.Input
        label={i18next.t("RA (°)")}
        value={ra}
        onChange={(e) => setRa(e.target.value)}
        placeholder="0 - 360"
      />
      <Form.Input
        label={i18next.t("Dec (°)")}
        value={dec}
        onChange={(e) => setDec(e.target.value)}
        placeholder="-90 - 90"
      />
      <Form.Input
        label={i18next.t("Radius (°)")}
        value={radius}
        onChange={(e) => setRadius(e.target.value)}
        placeholder="e.g. 1.0"
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

ConeSearchInputsComponent.propTypes = {
  currentQueryState: PropTypes.object.isRequired,
  updateQueryState: PropTypes.func.isRequired,
  active: PropTypes.bool.isRequired,
  onToggle: PropTypes.func.isRequired,
};

const ConeSearchInputs = withState(ConeSearchInputsComponent);

/**
 * Observation night range filter: min/max dates (YYYY-MM-DD in the UI,
 * converted to the stored YYYYMMDD keyword format on submit).
 *
 * Mirrors the original FRAM archive, which exposed "night" as a direct
 * date input rather than a browsable facet (too many distinct values for
 * a checkbox list to be usable). Stored as a single "metadata.
 * observation_night" filter carrying a "YYYYMMDD..YYYYMMDD" range string
 * (either bound may be omitted for an open-ended range), consumed by the
 * custom RangeQueryFacet registered for this field (see
 * models/fram/facets.py).
 */
const NightFilterComponent = ({
  currentQueryState,
  updateQueryState,
  active,
  onToggle,
}) => {
  const [nightFrom, setNightFrom] = useState("");
  const [nightTo, setNightTo] = useState("");

  const apply = () => {
    if (!nightFrom && !nightTo) return;
    const from = nightFrom ? nightFrom.replaceAll("-", "") : ""; // YYYY-MM-DD -> YYYYMMDD
    const to = nightTo ? nightTo.replaceAll("-", "") : "";
    updateQueryState({
      ...currentQueryState,
      filters: withFilter(
        currentQueryState.filters,
        "metadata.observation_night",
        `${from}..${to}`
      ),
    });
  };

  const clear = () => {
    setNightFrom("");
    setNightTo("");
    updateQueryState({
      ...currentQueryState,
      filters: withoutFilter(
        currentQueryState.filters,
        "metadata.observation_night"
      ),
    });
  };

  return (
    <FilterPanel
      label={i18next.t("Observation night")}
      active={active}
      onToggle={onToggle}
    >
      <Form.Input
        type="date"
        label={i18next.t("From")}
        value={nightFrom}
        onChange={(e) => setNightFrom(e.target.value)}
      />
      <Form.Input
        type="date"
        label={i18next.t("To")}
        value={nightTo}
        onChange={(e) => setNightTo(e.target.value)}
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

NightFilterComponent.propTypes = {
  currentQueryState: PropTypes.object.isRequired,
  updateQueryState: PropTypes.func.isRequired,
  active: PropTypes.bool.isRequired,
  onToggle: PropTypes.func.isRequired,
};

const NightFilter = withState(NightFilterComponent);

/**
 * Generic min/max numeric range filter factory, used for continuous float
 * fields (altitude, azimuth, exposure) where a checkbox facet is unusable
 * but a range query is the natural fit. Sends a single "min..max" range
 * string (either bound may be omitted for an open-ended range), consumed
 * by the custom RangeQueryFacet registered for these fields (see
 * models/fram/facets.py).
 */
const makeRangeFilter = (filterKey, labelText, minPlaceholder, maxPlaceholder) => {
  const RangeFilterComponent = ({
    currentQueryState,
    updateQueryState,
    active,
    onToggle,
  }) => {
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
        return;
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
      <FilterPanel label={labelText} active={active} onToggle={onToggle}>
        <Form.Input
          label={i18next.t("Min")}
          value={min}
          onChange={(e) => setMin(e.target.value)}
          placeholder={minPlaceholder}
        />
        <Form.Input
          label={i18next.t("Max")}
          value={max}
          onChange={(e) => setMax(e.target.value)}
          placeholder={maxPlaceholder}
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

  RangeFilterComponent.propTypes = {
    currentQueryState: PropTypes.object.isRequired,
    updateQueryState: PropTypes.func.isRequired,
    active: PropTypes.bool.isRequired,
    onToggle: PropTypes.func.isRequired,
  };

  return withState(RangeFilterComponent);
};

const AltitudeFilter = makeRangeFilter(
  "metadata.alt_az.altitude",
  i18next.t("Altitude (°)"),
  "0",
  "90"
);

const AzimuthFilter = makeRangeFilter(
  "metadata.alt_az.azimuth",
  i18next.t("Azimuth (°)"),
  "0",
  "360"
);

const ExposureFilter = makeRangeFilter(
  "metadata.exposure",
  i18next.t("Exposure (s)"),
  "0",
  "e.g. 30"
);

/**
 * Generic free-text input filter factory, used for high-cardinality /
 * unique-per-record fields (filename, target, title) where a checkbox
 * facet list would be unusable, but a plain aggregation facet also
 * doesn't fit -- the user types a fragment and it's matched against the
 * field.
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

const FilenameFilter = makeTextFilter(
  "metadata.filename",
  i18next.t("Filename"),
  i18next.t("e.g. 20170814041208-419-RA.fits")
);

const TargetFilter = makeTextFilter(
  "metadata.target",
  i18next.t("Target"),
  i18next.t("e.g. VAOD_color")
);

/**
 * Title filter: unlike Filename/Target (our own keyword fields), "title"
 * comes from the CCMM/RDM preset (`fulltext+keyword` type) and is matched
 * via an exact-match `term` query against its `.keyword` sub-field (see
 * ExactMatchFacet in models/fram/facets.py) rather than a substring
 * `wildcard` query -- simpler/more robust against upstream mapping
 * changes we don't control. The input is otherwise identical to the
 * other text filters; only the server-side query semantics differ.
 */
const TitleFilter = makeTextFilter(
  "metadata.title",
  i18next.t("Title"),
  i18next.t("Exact title match")
);

/**
 * Definition of every custom filter panel, in display order. Each entry's
 * `key` matches a unique identifier tracked in the parent's `openPanels`
 * state (see CustomFilters below) -- deliberately NOT the react-searchkit
 * filter key (some panels, like cone search, don't map 1:1 to a single
 * metadata field).
 */
const FILTER_PANELS = [
  { key: "cone_search", Component: ConeSearchInputs },
  { key: "observation_night", Component: NightFilter },
  { key: "altitude", Component: AltitudeFilter },
  { key: "azimuth", Component: AzimuthFilter },
  { key: "exposure", Component: ExposureFilter },
  { key: "target", Component: TargetFilter },
  { key: "filename", Component: FilenameFilter },
  { key: "title", Component: TitleFilter },
];

/**
 * Combined custom filters block. Standard checkbox facets (site, type,
 * ccd, camera_serial, filter, binning -- see AddFacetGroup in
 * models/fram/model.py) are rendered first via <SearchAppFacets>,
 * followed by the custom input-based filters below, each collapsed into
 * an accordion panel (see FilterPanel above) so a single narrow sidebar
 * column can hold all of them without overflowing into the results
 * column. `exclusive={false}` lets multiple panels stay open at once
 * (e.g. Altitude + Azimuth together).
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
