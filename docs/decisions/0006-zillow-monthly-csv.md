# 0006: Load Zillow from published CSVs, outside the weekly job

**Status:** Accepted, 2026-11-03

## Situation

Franklin's online history is too short for year-over-year comparisons, and a window running from spring into fall
can't separate a real price change from the seasonal pattern. Zillow's Home Value Index goes back to 2000 by county
and ZIP. Zillow's data page says its research data is free for public use with clear attribution. A third-party
summary says its general Terms of Use bar automated access; the terms themselves haven't been read. It's unclear
whether a script downloading a published file would fall under that.

## Decision

Keep exposure small:

- **Download only the published CSV files,** and never crawl Zillow pages.
- **Check `Last-Modified` first,** and skip the download if the file hasn't changed.
- **Run it monthly and by hand,** outside the weekly job. Zillow updates on the 16th.
- **Allow `--file`** for a copy downloaded by hand, which needs no network at all.
- **Carry attribution everywhere:** logged with each load, printed by `report`, and written to `ATTRIBUTION.txt` on
  export.

## Consequences

- **Year-over-year figures are available now,** without waiting for a year of Franklin data.
- **The index isn't a sale price.** It's a smoothed, modeled value, so it can't be compared dollar for dollar with
  medians from actual sales.
- **Monthly use is a convention.** Nothing stops an extra run, though an unchanged file isn't downloaded again.
- **Some ambiguity remains.** Read the Terms of Use before publishing this data. If the ambiguity is unacceptable,
  use `--file` only.
