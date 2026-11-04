# 0002: Build layers as plain tables and views

**Status:** Accepted, 2026-11-03

## Situation

The pipeline needs clear separation between source data, cleaned data and summaries. Sources also differ in
detail: county data has one row per sale, while Redfin and Zillow are already summarized by area and period.

## Decision

Use three layers, with no extra schemas or framework:

| Layer | Contents |
|---|---|
| Raw | `raw_page` only. County, Redfin and Zillow files aren't retained by the pipeline. |
| Cleaned | `auditor_report`, `auditor_sale`, `redfin_columbus_weekly`, `zillow_zhvi`, `v_sale_clean` |
| Summary | `v_county_week`, `v_county_rolling4`, `v_zip_month`, `v_zillow_yoy` |

When sources are joined, join them only at a matching level of detail, such as county by week or ZIP by month.
Never attach Redfin or Zillow figures to individual sales. No cross-source view exists yet.

## Consequences

- **Definitions live in version control** in `sql/`, and views are recreated on every connect.
- **There's little to operate.** Views recalculate on each query, which is fine at this data size.
- **Layers are a convention, not a boundary.** Nothing stops a query from skipping one.
- **Only Franklin can be rebuilt from raw.** Reloading the other sources means keeping or re-obtaining their files.
- **Changing an existing table needs a manual `ALTER`.** `schema.sql` only creates missing tables.

Revisit this if data volume grows or the pipeline moves to a platform with managed tables.
