# 0001: Keep raw report pages

**Status:** Accepted, 2026-11-03

## Situation

Franklin County's weekly report pages appear to drop off the site after roughly 30 weeks. That's inferred from
the listing's count of 30 reports and from older guessed URLs returning 404. Originally only parsed rows were
stored, so once a page was gone, a parser bug could never be corrected for that week.

## Decision

Save every report page fetched in `raw_page` before parsing it. A refetch adds a row only if the content changed.
`python run.py reparse` re-parses the latest saved copy of each page without touching the network.

The listing page and guessed-URL checks aren't saved, and neither are files from other sources.

## Consequences

- **It has already paid off.** April 2026 pages used a different format, and two weeks loaded no sales. After
  the parser fix, a re-parse recovered 734 sales with no new requests.
- **The database will soon hold data that can't be fetched again,** so it needs a backup. SQL Server shows no
  backups of this database as of 2026-11-04.
- **Pages are stored as decoded text, not original bytes.** They aren't byte-exact, though no damage is known.
- **A re-parse adds missed sales and refreshes report summaries, but doesn't correct stored sales.** Price is part
  of the sale key, so a corrected price would be inserted next to the wrong one. Delete the affected rows first.
