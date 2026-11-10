# Quality rules

Every check on the data, by the quality dimension it covers. The names in the first column are the names in the
code, and CI fails if a rule or expectation is missing from this page.

## How a failure is handled

| Severity | Where | What happens |
|---|---|---|
| Fail | `python run.py check`, in the weekly job | The check exits 1. The weekly job still takes its backup, then skips landing, the pipeline run and reconciliation, so bad rows never reach append-only bronze |
| Warn | The same check | Printed for review. Blocks nothing |
| Drop | A pipeline expectation in silver | The row is left out of silver and counted. Bronze still has it |
| Count | A pipeline expectation in silver | The row is kept and counted |

A violation that was investigated and accepted is recorded in `KNOWN` in
[`pipeline/quality.py`](../../pipeline/quality.py), with what was found, and stops being reported.

## Rules on SQL Server

23 rules in [`pipeline/quality.py`](../../pipeline/quality.py): 15 fail, 8 warn.

| Rule | Dimension | Severity | Catches |
|---|---|---|---|
| `report_has_sales` | Completeness | Fail | A report that loaded no sales |
| `franklin_raw_page_saved` | Completeness | Fail | A Franklin report with no saved page, which could never be re-parsed |
| `zillow_counties_present` | Completeness | Fail | A county missing from Zillow |
| `weekly_volume_dip` | Completeness | Warn | A newest week with under half the usual residential sales |
| `sale_price_positive` | Validity | Fail | A price of zero or less |
| `sale_date_not_future` | Validity | Fail | A sale dated after today |
| `allowed_values` | Validity | Fail | A county or report type the pipeline doesn't know |
| `franklin_parcel_format` | Validity | Fail | A Franklin parcel ID not shaped like 123-456789-00 |
| `report_period_valid` | Validity | Fail | A report week that is blank or runs backwards |
| `zillow_value_positive` | Validity | Fail | A Zillow value of zero or less |
| `redfin_regions` | Validity | Fail | Redfin holding anything other than the Columbus metro and three counties |
| `redfin_dates` | Validity | Fail | A Redfin date column with values before 2000 |
| `franklin_zip_prefix` | Validity | Warn | A Franklin sale whose ZIP is blank or doesn't start with 43 |
| `residential_price_cap` | Validity | Warn | A residential sale over $5M |
| `report_covers_7_days` | Validity | Warn | A report week that isn't 7 days long |
| `published_count_matches` | Accuracy | Fail | Parsed rows differing from the county's printed count |
| `parsed_matches_page` | Accuracy | Fail | Parsed rows differing from the parcel IDs found in the saved page |
| `zillow_monthly_change` | Accuracy | Warn | A Zillow value moving over 10% in a month |
| `sale_type_matches_report` | Consistency | Fail | A sale whose type differs from its report's |
| `sale_date_near_report_week` | Consistency | Fail | A sale dated before its report's week, or over 7 days after it |
| `sale_in_report_week` | Consistency | Warn | A report with sales dated outside its week |
| `report_period_unique` | Uniqueness | Warn | Two reports giving the same week |
| `weekly_cadence` | Timeliness | Warn | Reports not 7 days apart, so a week may be missing |

## Expectations in Databricks silver

In [`databricks/pipelines/silver.py`](../../databricks/pipelines/silver.py).

| Rule | Dimension | Severity | Table | Catches |
|---|---|---|---|---|
| `has_sale_date` | Completeness | Drop | `silver_sale` | A sale date that is missing or didn't parse |
| `has_sale_price` | Completeness | Drop | `silver_sale` | A sale price that is missing or didn't parse |
| `has_zip` | Completeness | Count | `silver_sale` | A sale with no ZIP |
| `has_period` | Completeness | Count | `silver_report` | A report with no week |
| `has_value` | Completeness | Drop | `silver_zillow_county` | A month with no Zillow value |

## Checks that aren't rules

These protect the same dimensions but run at a different point, so they aren't in the two lists above.

| Check | Dimension | Where | What it does |
|---|---|---|---|
| Sale primary key | Uniqueness | `auditor_sale` in [`schema.sql`](../../sql/schema.sql) | County, parcel, date and price can't repeat, so a re-run adds nothing |
| Raw page unique index | Uniqueness | `raw_page` in `schema.sql` | The same page content is saved once |
| Latest version | Uniqueness | `_latest` in `silver.py` | Bronze keeps every version; silver keeps one row per key |
| Reconciliation | Consistency | [`reconcile.py`](../../databricks/reconcile.py) | Silver must match SQL Server on row counts, totals and date ranges for sales and reports |
| Cut-off file guard | Completeness | [`zillow.py`](../../pipeline/zillow.py) | A Zillow file with under 95% of the rows already loaded is refused |
| Stale run | Timeliness | `run_problems` in [`auditor.py`](../../pipeline/auditor.py) | A run counts as failed if the newest week is over 14 days old |
| Land use filter | Validity | [`county_file.py`](../../pipeline/county_file.py) | A county file whose land use filter keeps nothing raises an error. A file with no land use column isn't filtered at all |

## Gaps

- **Thresholds come from the first 59 reports.** The $5M cap, the 50% volume dip and the 10% Zillow move were set
  from what had loaded by then.
- **No alert.** A failed weekly job writes a log and a non-zero exit code. Nothing sends a message.
- **Zillow isn't reconciled** between SQL Server and Databricks.
- **A county file with no land use column loads unfiltered.** Every row is labeled residential, and only a log line
  shows that no filter ran. No rule catches a commercial sale that arrives this way.
- **Expectation counts aren't tracked over time.** Each pipeline update records them; nothing reads them back.
