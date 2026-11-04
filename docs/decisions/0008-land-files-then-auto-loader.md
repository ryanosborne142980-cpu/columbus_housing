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

Only Zillow's county file runs this way so far. The SQL Server pipeline is unchanged and still does the rest.

## Consequences

- **Files are kept twice,** locally in `data/landing/` and in the volume, so this source could be replayed, though that is untested.
- **Auto Loader's file tracking replaces custom code** for skipping processed files. A second run added no rows.
- **Two systems now hold Zillow data,** SQL Server and Databricks, with no reconciliation between them.
- **Each monthly Zillow file repeats its full history,** so bronze will hold repeated rows by design. Silver has to
  pick the latest release.
- **This runs on Free Edition.** That shows familiarity with the tools, not production experience, and Free Edition
  isn't for commercial use.
