# 0005: Make Redfin a manual download

**Status:** Accepted, 2026-11-03

## Situation

The loader defaulted to Redfin's public S3 weekly file. That file was last modified on March 26, 2025, so a
successful load would have quietly delivered data 19 months old. The market-tracker paths tried on the same bucket
return 403, and the May 2026 Data Center's download links appear to be rendered by JavaScript. Loading the 725 MB
compressed all-US file reached 6.8 GB of memory before the run was stopped.

## Decision

Remove the default URL. `redfin` requires `--file` or `--url`, and `all` skips Redfin without one. Files are read
in 200,000-row chunks and filtered to Columbus-area rows as they go.

## Consequences

- **Stale data can't arrive by default.** The cost is a manual step for each update. Nothing checks how old a
  supplied file is, so check its newest `period_end` after loading.
- **Chunked reading is only proven on small test files.** No real all-US file has been loaded this way yet. `--file`
  reads in chunks, but `--url` still holds the whole download in memory first.
- **Redfin is often behind.** It's only as fresh as the last download, even though Redfin publishes weekly.
- **Attribution is included as a precaution.** `report` prints a Redfin source line. Redfin's own terms still
  need to be checked directly before publishing its data.
