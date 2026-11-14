# Quality rules

## SQL Server rules (`pipeline/quality.py`, run by `python run.py check`)

A fail exits 1 and stops the weekly job landing anything in Databricks. A warn is printed for review.

| Rule | Dimension | Severity |
|---|---|---|
| `sale_type_matches_report` | Consistency | fail |
| `sale_price_positive` | Validity | fail |
| `sale_date_not_future` | Validity | fail |
| `sale_date_near_report_week` | Consistency | fail |
| `allowed_values` | Validity | fail |
| `franklin_parcel_format` | Validity | fail |
| `report_has_sales` | Completeness | fail |
| `published_count_matches` | Accuracy | fail |
| `parsed_matches_page` | Accuracy | fail |
| `report_period_valid` | Validity | fail |
| `franklin_raw_page_saved` | Completeness | fail |
| `zillow_counties_present` | Completeness | fail |
| `zillow_value_positive` | Validity | fail |
| `redfin_regions` | Completeness | fail |
| `redfin_dates` | Validity | fail |
| `franklin_zip_prefix` | Validity | warn |
| `residential_price_cap` | Validity | warn |
| `report_covers_7_days` | Consistency | warn |
| `report_period_unique` | Uniqueness | warn |
| `weekly_cadence` | Timeliness | warn |
| `weekly_volume_dip` | Completeness | warn |
| `zillow_monthly_change` | Accuracy | warn |
| `sale_in_report_week` | Consistency | warn |

Checked exceptions are listed in `KNOWN` in `pipeline/quality.py`.

## Pipeline expectations (`databricks/pipelines/silver.py`)

| Expectation | Table | Dimension | Action |
|---|---|---|---|
| `has_sale_date` | `silver_sale_typed` | Completeness | drop row |
| `has_sale_price` | `silver_sale_typed` | Completeness | drop row |
| `has_zip` | `silver_sale` | Completeness | record only |
| `has_period` | `silver_report` | Completeness | record only |
| `has_value` | `silver_zillow_county` | Completeness | drop row |

## Other guards

- `databricks/reconcile.py` compares Databricks to SQL Server on counts, totals, ranges and medians.
- `pipeline/zillow.py` refuses to replace loaded Zillow data with a file that has fewer rows.
