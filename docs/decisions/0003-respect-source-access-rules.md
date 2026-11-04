# 0003: Respect source access rules, with no workarounds

**Status:** Accepted, 2026-11-03

## Situation

The pipeline collects data from public websites. Some of those sites limit automated access, and some sources
would be useful despite those limits.

## Decision

All web requests go through `pipeline/http.py`, which:

- **Identifies itself** with a descriptive user agent.
- **Honors robots.txt.** A 401 or 403 on robots.txt means disallowed. A 5xx refuses for now and checks again
  on the next request.
- **Limits its rate** to at most one request per host every 2 seconds, or the site's Crawl-delay if longer.
- **Backs off** on 429 and 503, honoring `Retry-After`, with capped retries.

If a source blocks automated access, the pipeline doesn't get around it. Manual download by a person, where the
source allows it, is the fallback.

## Consequences

- **Franklin's Daily Conveyance page is unused,** because robots.txt disallows it. The weekly reports are used
  instead.
- **Licking County is a manual source.** `ontrac.lickingcounty.gov` is behind a Cloudflare bot check and its
  robots.txt returns 403.
- **Some data arrives later or by hand,** and that's accepted as the cost.
- **Redirects aren't re-checked.** `requests` follows them without another robots check. Current sources don't
  redirect to other hosts, so this is noted in `http.py` rather than handled.
