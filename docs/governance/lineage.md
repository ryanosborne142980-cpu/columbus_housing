# Lineage

## County sales

| Hop | Code | Output |
|---|---|---|
| County report page to saved page | `pipeline/auditor.py`, `pipeline/db.py` | `raw_page` |
| Saved page to parsed rows | `pipeline/auditor.py` (`python run.py reparse` re-reads `raw_page`) | `auditor_report`, `auditor_sale` |
| Delaware or Licking export file to rows | `pipeline/county_file.py` | `auditor_report` (`file:` URLs), `auditor_sale` |
| Clean sales | `sql/views.sql` | `v_sale_clean`, then `v_county_week`, `v_county_rolling4`, `v_zip_month` |
| SQL Server to volume | `databricks/land_sql_tables.py` | `auditor_sale`, `auditor_report` files |
| Volume to bronze | `databricks/pipelines/bronze.py` | `bronze_auditor_sale`, `bronze_auditor_report` |
| Bronze to silver | `databricks/pipelines/silver.py` | `silver_sale` (via `silver_sale_typed`), `silver_report` |
| Check against SQL Server | `databricks/reconcile.py` | pass or fail |

## Zillow

| Hop | Code | Output |
|---|---|---|
| Zillow CSV to SQL Server | `pipeline/zillow.py` | `zillow_zhvi`, `zillow_load_log`; view `v_zillow_yoy` |
| Zillow CSV to volume | `databricks/land_zillow.py` | `zillow_county` files |
| Volume to bronze to silver | `bronze.py`, `silver.py` | `bronze_zillow_county`, `silver_zillow_county` |

## Redfin

Manual download, loaded by `pipeline/redfin.py` into `redfin_columbus_weekly` and `redfin_load_log`. Not in Databricks.

## Derived columns

| Column | Derived from | Rule |
|---|---|---|
| `v_sale_clean.parcel_id`, `site_address` | `auditor_sale` | Minimum across parcels on one deed |
| `parcel_count` | `auditor_sale` | Count of rows grouped into one sale |
| `week_start` | `sale_date` | Monday of the sale's week |
| `month` | `sale_date` | YYYY-MM |
| `silver_sale.*` | `bronze_auditor_sale` | Typed, latest version per sale key, residential, $10,000 or more, collapsed like `v_sale_clean` |
| `silver_zillow_county.county` | `RegionName` | Trailing " County" removed |
| `silver_zillow_county.month`, `zhvi` | Zillow month-end columns | Unpivoted; month truncated to first day |
