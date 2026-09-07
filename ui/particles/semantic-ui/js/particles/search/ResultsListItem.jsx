import React from "react";
import PropTypes from "prop-types";
import _get from "lodash/get";
import _join from "lodash/join";
import { Grid, Item, Label } from "semantic-ui-react";
import { i18next } from "@translations/i18next";

export const ResultsListItem = ({ result, ...rest }) => {
  const accessRights = _get(result, "ui.access_status", null);
  const createdDateRaw = _get(result, "ui.created_date_l10n_short", null);
  const formatDateToDDMMYYYY = (s) => {
    if (!s) return null;
    const m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/);
    if (m) {
      const month = m[1].padStart(2, "0");
      const day = m[2].padStart(2, "0");
      let year = m[3];
      if (year.length === 2) year = "20" + year;
      return `${day}.${month}.${year}`;
    }
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      return `${String(d.getDate()).padStart(2, "0")}.${String(
        d.getMonth() + 1
      ).padStart(2, "0")}.${d.getFullYear()}`;
    }
    return s;
  };
  const createdDate = formatDateToDDMMYYYY(createdDateRaw) || "No creation date found.";
  const languages = _get(result, "metadata.languages", []);
  const version = _get(result, "metadata.version", null);
  const title = _get(result, "metadata.title", i18next.t("No title"));
  return (
    <Item key={result.id} data-testid="result-item">
      <Item.Content>
        <Grid>
          <Grid.Row>
            <Grid.Column className="results-list item-main">
              <div className="justify-space-between flex">
                <Item.Header as="h2">
                  <a href={result.links.self_html}>{title}</a>
                </Item.Header>
                <div className="item-access-rights">
                  {result.state && (
                    <Label title={result.state_timestamp}>{result.state}</Label>
                  )}
                  {accessRights && accessRights.id !== "open" && (
                    <Label title={`${accessRights.description_l10n}`}>
                      {accessRights.title_l10n}
                    </Label>
                  )}
                </div>
              </div>
              <Item.Meta>
                <Grid columns={1}>
                  <Grid.Column>
                    <Grid.Row className="ui separated">
                      <span
                        aria-label={i18next.t("Languages")}
                        title={i18next.t("Languages")}
                      >
                        {_join(
                          languages.map((l) => l.title),
                          ", "
                        )}
                      </span>
                    </Grid.Row>
                  </Grid.Column>
                </Grid>
              </Item.Meta>
              <Item.Extra>
                <div>
                  <small>
                    <p>
                      {createdDate && (
                        <>
                          {i18next.t("Uploaded on")} <span>{createdDate}</span>{" "}
                          {version && `(${i18next.t("version")}: ${version})`}
                        </>
                      )}
                    </p>
                  </small>
                </div>
              </Item.Extra>
            </Grid.Column>
          </Grid.Row>
        </Grid>
      </Item.Content>
    </Item>
  );
};

ResultsListItem.propTypes = {
  result: PropTypes.object.isRequired,
};

export default ResultsListItem;
