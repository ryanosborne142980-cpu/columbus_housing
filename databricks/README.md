# Bronze on Databricks

Lands source files raw and append-only with Auto Loader, in a pipeline deployed from this folder. Tables:
`bronze_auditor_sale`, `bronze_auditor_report` and `bronze_zillow_county`.

| Piece | Where |
|---|---|
| Schema, volume, pipeline | [databricks.yml](databricks.yml) |
| Auto Loader table | [pipelines/bronze.py](pipelines/bronze.py) |
| Zillow file to volume | [land_zillow.py](land_zillow.py) |
| New SQL Server rows to volume | [land_sql_tables.py](land_sql_tables.py) |

## How it works

1. `land_zillow.py` downloads Zillow's county file locally and uploads it unchanged to the `raw` volume. Each
   file name carries Zillow's Last-Modified date.
2. `land_sql_tables.py` exports `auditor_sale` and `auditor_report` rows added since its last run to CSV and uploads
   them. SQL Server only listens on localhost, so Databricks can't connect to it directly.
3. Auto Loader picks up new files and appends their rows to the matching bronze table.
4. Every value stays a string. Each row records `source_file`, `source_modified_at` and `loaded_at`.

## Run it

You need the Databricks CLI, logged in under a profile named `columbus`.

```bash
databricks bundle deploy -p columbus     # from this folder
python databricks/land_zillow.py         # from the repo root
python databricks/land_sql_tables.py     # from the repo root
databricks bundle run bronze -p columbus # from this folder
```

## What's been tested

On Databricks Free Edition, 2026-11-04:

- **Load:** 3,071 rows and 330 source columns, matching the source file, plus the metadata columns and
  `_rescued_data`.
- **County tables:** 12,718 sales and 59 reports, matching SQL Server on row counts, price totals, date ranges and
  parsed-row totals. A sample sale matched field by field.
- **Re-run:** a second run added no rows, and `loaded_at` stayed the same.
- **Nothing new:** landing again with no new rows uploads no file.

**Not tested yet:**

- **Schema drift.** Zillow adds a column every month, so the next release should trigger it. In the
  `addNewColumns` mode set here, Databricks documents that the stream stops once, adds the column, and continues
  on restart.
- **A second file.** Each monthly file holds Zillow's full history, so appending it will repeat every region.
  Picking the latest release belongs in silver.
- **Replay from the volume.**
- **A later batch of new rows on real data.** Only a test on sample rows has covered that so far.

Credit Zillow wherever this data is shown. See [decision 0006](../docs/decisions/0006-zillow-monthly-csv.md) and
[decision 0008](../docs/decisions/0008-land-files-then-auto-loader.md).
