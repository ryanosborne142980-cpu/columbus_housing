# 0008: Download locally, then load with Auto Loader

**Status:** Accepted, 2026-11-04

## Situation

The bronze layer should land data raw and append-only, with enough metadata to trace each row and no duplicates on
re-run. Databricks' [Free Edition limits](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations)
say outbound internet is restricted to a set of trusted domains. Whether Zillow's file host is reachable from there
wasn't tested.

## Decision

Download on the local machine through `pipeline/http.py`, so robots.txt and rate limits still apply. Upload the file
unchanged to a Unity Catalog volume, and let Auto Loader load it into a streaming table. The schema, volume and
pipeline are deployed from `databricks/` as an asset bundle.

County sales and report summaries travel the same way. SQL Server only listens on localhost, so a direct connection
isn't possible, and opening the laptop's database to the internet was ruled out. `land_sql_tables.py` exports only
rows added since its last run.

Redfin and the Delaware and Licking files aren't landed yet. The SQL Server pipeline remains the system that loads
and validates the county data.

## Consequences

- **Files are kept twice,** locally in `data/landing/` and in the volume, so this source could be replayed, though that is untested.
- **Auto Loader's file tracking replaces custom code** for skipping processed files. A second run added no rows.
- **SQL Server is still the source for county data.** Databricks only sees it after a landing run, and nothing
  automatically reconciles the two.
- **A re-parsed report is exported again,** because its `fetched_at` changes. Bronze keeps both versions, and silver
  has to pick the latest.
- **Each monthly Zillow file repeats its full history,** so bronze will hold repeated rows by design. Silver has to
  pick the latest release.
- **This runs on Free Edition.** That shows familiarity with the tools, not production experience, and Free Edition
  isn't for commercial use.
