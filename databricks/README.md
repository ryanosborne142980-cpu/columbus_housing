# Bronze on Databricks

Lands source files raw and append-only with Auto Loader, in a pipeline deployed from this folder.

| Piece | Where |
|---|---|
| Schema, volume, pipeline | [databricks.yml](databricks.yml) |
| Auto Loader table | [pipelines/bronze.py](pipelines/bronze.py) |
| Download and upload | [land_zillow.py](land_zillow.py) |

## How it works

1. `land_zillow.py` downloads Zillow's county file locally and uploads it unchanged to the `raw` volume. Each
   file name carries Zillow's Last-Modified date.
2. Auto Loader picks up new files and appends their rows to `bronze_zillow_county`.
3. Every value stays a string. Each row records `source_file`, `source_modified_at` and `loaded_at`.

## Run it

You need the Databricks CLI, logged in under a profile named `columbus`.

```bash
databricks bundle deploy -p columbus     # from this folder
python databricks/land_zillow.py         # from the repo root
databricks bundle run bronze -p columbus # from this folder
```

## What's been tested

On Databricks Free Edition, 2026-11-04:

- **Load:** 3,071 rows and 330 source columns, matching the source file, plus the metadata columns and
  `_rescued_data`.
- **Re-run:** a second run added no rows, and `loaded_at` stayed the same.

**Not tested yet:**

- **Schema drift.** Zillow adds a column every month, so the next release should trigger it. In the
  `addNewColumns` mode set here, Databricks documents that the stream stops once, adds the column, and continues
  on restart.
- **A second file.** Each monthly file holds Zillow's full history, so appending it will repeat every region.
  Picking the latest release belongs in silver.
- **Replay from the volume.**

Credit Zillow wherever this data is shown. See [decision 0006](../docs/decisions/0006-zillow-monthly-csv.md) and
[decision 0008](../docs/decisions/0008-land-files-then-auto-loader.md).
