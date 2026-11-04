# 0004: Find Franklin reports by guessing URLs past the listing

**Status:** Accepted, 2026-11-03

## Situation

A two-year backfill loaded only 10 weeks and reported no error. The county's listing shows 10 reports per page,
and its "Next" button is an ASP.NET postback, so the `&page=` parameter the code sent was ignored. The fallback
to guessing URLs only ran when the listing returned nothing at all.

## Decision

Read the listing's first page, then guess URLs week by week for anything older, trying known URL patterns and
dates within a day of each Sunday. Stop at the `--since` date, or after 4 weeks in a row with no page.

Driving the postback wasn't tried. It might find reports that guessing misses, so it's the next option if those
gaps matter.

## Consequences

- **Coverage grew from 10 to 28 residential weeks,** out of the 30 the listing counts.
- **Reports outside the known patterns are missed.** The May 29 – Jun 4, 2026 report is at a URL dated
  June 4, which guessing doesn't try. The [runbook](../runbook.md#known-gaps) tracks this.
- **Failed guesses cost requests:** 9 per missing week for residential and 6 for commercial. The 4-week stop limits
  this.
- **A long gap could stop discovery early.** Four missing weeks in a row would hide any older reports.
