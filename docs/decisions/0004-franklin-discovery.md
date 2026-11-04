# 0004: Find Franklin reports by guessing URLs past the listing

**Status:** Accepted, 2026-11-03

## Situation

A two-year backfill loaded only 10 weeks and reported no error. The county's listing shows 10 reports per page,
and its "Next" button is an ASP.NET postback, so the `&page=` parameter the code sent was ignored. The fallback
to guessing URLs only ran when the listing returned nothing at all.

## Decision

Read the listing's first page, then guess URLs week by week for anything older, trying known URL patterns and
dates within a day of each Sunday. Stop at the `--since` date, or after 4 weeks in a row with no page.

The listing's paging was later driven by hand to find two missed reports, using its page dropdown and Go button.
It isn't part of discovery. Paging code would be tied to the form's generated control names, which weren't evaluated
for stability.

## Consequences

- **Coverage grew from 10 to 28 residential weeks,** out of the 30 the listing counts. All 30, and all 29 commercial, are now loaded.
- **Reports outside the known patterns are missed.** Six 2026 reports were, found on page 3 of each listing and
  loaded with `run.py auditor --url`. Most used a name discovery didn't know yet, which has been added. Two are dated
  June 4, three days from their Sunday, so guessing would still miss them.
- **Failed guesses cost requests:** 12 per missing week for residential and 9 for commercial. The 4-week stop limits
  this.
- **A long gap could stop discovery early.** Four missing weeks in a row would hide any older reports.
