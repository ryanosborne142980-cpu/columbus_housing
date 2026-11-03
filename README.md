# Columbus Housing Trend Pipeline

Weekly Columbus-area housing trends from free, legitimate sources, landed in SQL Server.

| Source | Grain | Cadence | Gives you |
|---|---|---|---|
| Franklin County Auditor weekly sales reports | Parcel-level closed sales by ZIP | Published Sundays (Fri–Thu week) | Ground-truth prices and volume, ZIP-level |
| Delaware / Licking County Auditor sales exports | Parcel-level closed sales | Manual, on request | Same as Franklin, loaded from a file you obtain |
| Redfin Data Center weekly tracker | Columbus metro + Franklin/Delaware/Licking county rows, rolling 4-week | Thursdays | Leading indicators: new listings, pendings, inventory, DOM, price drops |

## Setup
Needs SQL Server (default: local instance `.\ROSBO_SQL`, Windows auth) and ODBC Driver 18 for SQL Server.
```bash
# Install the dependencies required to fetch, parse, and load the housing data.
pip install -r requirements.txt
# Run the automated checks (uses a throwaway database, columbus_housing_test, on the same instance).
python -m pytest -q
```
Data lands in database `columbus_housing` (created on first run). Override with `--server` / `--db`,
or env vars `COLUMBUS_HOUSING_SERVER` / `COLUMBUS_HOUSING_DB`. Schema changes to existing tables are not
applied automatically: `sql/schema.sql` only creates missing tables, while views are recreated on every run.

## Run
```bash
# Load every Franklin County report still online (the county keeps ~30 weeks).
python run.py auditor --since 2024-10-01      # backfill; stops when weeks run out; incremental after
# Re-parse saved raw pages after a parser fix (no network).
python run.py reparse
# Import a Delaware county sales export from a local Excel or CSV file.
python run.py county-file --county Delaware --file sales.xlsx   # CSV, TSV, .xls or .xlsx
# Download or import the Redfin market-tracker dataset for leading indicators.
python run.py redfin                           # default S3 URL; or --file <download from Redfin hub>
# Generate the reports and export every view to CSV files in the target folder.
python run.py report --export out/             # summary + CSVs of every view
# Run the regular weekly job for Franklin County and Redfin data only.
python run.py all --since 2026-10-01           # weekly job (Franklin + Redfin; not county files)
```
Schedule `python run.py all` weekly (Mon morning; both sources have published by then).
Re-runs are idempotent: loaded reports are skipped, and sales are keyed on county+parcel+date+price.

## Getting the Delaware and Licking files
- **Delaware:** at https://auditor.co.delaware.oh.us/propinfo/ choose The Whole County → Residential → Sold Since a Specific Date. The file arrives by email.
- **Licking:** no public bulk export. Request a residential sales file from the Licking County Auditor's office.

`county-file` finds columns by header name (`COLUMN_HINTS` in `pipeline/county_file.py`) and ignores owner and mailing columns. It keeps residential rows only (land use 500–599, or a class starting with R) and pulls the ZIP from the address when there's no ZIP column. If a load fails, the error lists the file's columns; add the missing header to `COLUMN_HINTS`. Check the logged column map on the first load of each county: matching is by substring, so a generic header like `date` can match the wrong column.

## Views (sql/views.sql)
- `v_sale_clean`: residential only, price >= $10k, multi-parcel deeds collapsed to one sale, per county
- `v_county_week`: weekly count, avg, and median per county
- `v_county_rolling4`: trailing 4-week pooled median + YoY per county. Same construction as Redfin's, so the series line up.
- `v_zip_month`: ZIP x month median + YoY, all counties pooled (some ZIPs cross county lines). YoY is suppressed below 10 sales per side.
- `v_report_validation`: parsed rows vs the county's own count. Non-zero `diff` means the parser has drifted.

## Known limits
- **Franklin reports stay online only ~30 weeks.** Every fetched page is saved verbatim in `raw_page`, so old weeks can be re-parsed after they disappear. Run the weekly job without gaps: a missed week is lost for good, and Franklin YoY needs a full year of captured weeks.
- **Delaware and Licking are manual and only as fresh as your last file.** Their YoY needs two years of history in the export. Fairfield, Union, Madison and Pickaway are still missing.
- **No property attributes** (sqft, beds, year built), so medians move with mix shift. Treat moves under ~3% as noise until you enrich via parcel lookup.
- **The $10k floor is a proxy** for arm's-length sales. It doesn't catch below-market related-party sales or bulk/portfolio deals.
- **Daily Conveyance is robots-disallowed** and deliberately unused. The code honors robots.txt everywhere.
- **Redfin default URL is the legacy S3 file.** After Redfin's May 2026 Data Center rebuild, verify it still updates; if not, download from https://www.redfin.com/news/data-center/downloads/ and use `--file`. The loader auto-detects CSV/TSV/gz and column names.
- **Parser** was built against the live page structure as of 2026-11-01. Check `v_report_validation` after your first run.
