# Bronze and silver on Databricks

Lands source files raw and append-only with Auto Loader, then builds typed, de-duplicated tables, in one pipeline
deployed from this folder.

| Bronze (raw, append-only) | Silver (typed, latest version) |
|---|---|
| `bronze_auditor_sale` | `silver_sale`: residential, $10k or more, multi-parcel deeds counted once |
| `bronze_auditor_report` | `silver_report`: the latest version of each report |
| `bronze_zillow_county` | `silver_zillow_county`: one row per month for three Ohio counties, from the latest release |

| Piece | Where |
|---|---|
| Schema, volume, pipeline | [databricks.yml](databricks.yml) |
| Auto Loader tables | [pipelines/bronze.py](pipelines/bronze.py) |
| Silver tables and data quality rules | [pipelines/silver.py](pipelines/silver.py) |
| Zillow file to volume | [land_zillow.py](land_zillow.py) |
| New SQL Server rows to volume | [land_sql_tables.py](land_sql_tables.py) |
| Silver compared with SQL Server | [reconcile.py](reconcile.py) |

## How it works

1. `land_zillow.py` downloads Zillow's county file locally and uploads it unchanged to the `raw` volume. Each
   file name carries Zillow's Last-Modified date.
2. `land_sql_tables.py` exports `auditor_sale` and `auditor_report` rows added since its last run to CSV and uploads
   them. SQL Server only listens on localhost, so Databricks can't connect to it directly.
3. Auto Loader picks up new files and appends their rows to the matching bronze table.
4. Bronze keeps every value as a string. Each row records `source_file`, `source_modified_at` and `loaded_at`.
5. Silver sets types, picks the latest version of each row, and applies data quality rules. A row with no sale date,
   sale price or Zillow value is dropped; a missing ZIP or report week is only counted.

## Run it

You need the Databricks CLI, logged in under a profile named `columbus`.

```bash
databricks bundle deploy -p columbus     # from this folder
python databricks/land_zillow.py         # from the repo root
python databricks/land_sql_tables.py     # from the repo root
databricks bundle run bronze -p columbus # from this folder
python databricks/reconcile.py           # from the repo root; exits 1 if silver differs from SQL Server
```

`reconcile.py` was run against the real tables on 2026-11-06 and matched: 12,038 clean sales and 59 reports, on row
counts, totals and date ranges. A real difference hasn't happened yet; only a unit test has covered that path.

## What's been tested

On Databricks Free Edition, 2026-11-04:

- **Load:** 3,071 rows and 330 source columns, matching the source file, plus the metadata columns and
  `_rescued_data`.
- **County tables:** 12,718 sales and 59 reports, matching SQL Server on row counts, price totals, date ranges and
  parsed-row totals. A sample sale matched field by field.
- **Re-run:** a second run added no rows, and `loaded_at` stayed the same.
- **Nothing new:** landing again with no new rows uploads no file.
- **Silver against SQL Server:** `silver_sale` matches `v_sale_clean` on 12,038 sales, price total, parcel count and
  date range. Counts and medians match for all 31 weeks in `v_county_week`. `silver_report` and
  `silver_zillow_county` match on row counts and totals.

**Not tested yet:**

- **Schema drift.** Zillow adds a column every month, so the next release should trigger it. In the
  `addNewColumns` mode set here, Databricks documents that the stream stops once, adds the column, and continues
  on restart.
- **A second Zillow file.** Each monthly file holds Zillow's full history, so bronze will repeat every region.
  Silver is written to pick the latest release, but no second release has arrived to prove it.
- **Silver's latest-version logic on real repeats.** Every row has only one version so far.
- **Data quality rules dropping a bad row.** `has_sale_date` and `has_sale_price` now run on `silver_sale_typed`,
  before the residential and price filter, so they should count the bad rows in stage 4 of `drift_test.py`
  (expected: 2 and 1). That run hasn't been done yet.
- **Replay from the volume.**
- **A later batch of new rows on real data.** Only a test on sample rows has covered that so far.

`silver_sale` repeats the rules in `v_sale_clean`, so a change to one has to be made in both.

Credit Zillow wherever this data is shown. See [decision 0006](../docs/decisions/0006-zillow-monthly-csv.md) and
[decision 0008](../docs/decisions/0008-land-files-then-auto-loader.md).
