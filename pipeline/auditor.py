"""Franklin County Auditor weekly sales reports -> auditor_sale.

Source: https://auditor.franklincountyohio.gov/News-articles  (weekly, published Sundays,
covering Fri-Thu). The Daily Conveyance page is robots-disallowed, so it is NOT used.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from . import db, http

log = logging.getLogger(__name__)

BASE = "https://auditor.franklincountyohio.gov"
LISTING = {
    "residential": BASE + "/News-articles?dlv_OC%20CL%20Auditor%20News%20Listing="
    "%28dd_OC%20News%20Categories%3DWeekly%20Residential%20Home%20Sales%20Report%29",
    "commercial": BASE + "/News-articles?dlv_OC%20CL%20Auditor%20News%20Listing="
    "%28dd_OC%20News%20Categories%3DWeekly%20Commercial%20Sales%20Report%29",
}
# Slugs the county has actually used (inconsistent over time).
# These filename patterns keep the weekly report discovery resilient when the site's URLs change
# across years or publication formats.
SLUG_GUESSES = {
    "residential": ["{d}-WHSR", "{d}-Residential-Sales-Report", "{d}-Home-Sales",
                    "{d}-Weekly-Home-Sales-Report"],
    "commercial": ["{d}-WCSR", "{d}-Commercial-Sales", "{d}-Commercial-Sales-Report"],
}

_PERIOD_RE = re.compile(
    r"(?:week of|from)\s+([A-Z][a-z]+\.?\s+\d{1,2})(?:,?\s+(\d{4}))?\s+(?:through|to|-)\s+"
    r"([A-Z][a-z]+\.?\s+\d{1,2}),?\s+(\d{4})"
)
# Older pages (Apr 2026) shorten the week: "week of Apr. 3–9", "past week (April 10 - April 16)" or
# "week of April 17 through 23, 2026". The year comes from the publish date.
_PERIOD_NOYEAR_RE = re.compile(
    r"(?:week of|past week \()\s*([A-Z][a-z]+\.?\s+\d{1,2})\s*(?:through|to|[-\u2013\u2014])\s*"
    r"([A-Z][a-z]+\.?\s+)?(\d{1,2})\b"
)
_PUBLISHED_RE = re.compile(r"Published on\s+(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})")
_ZIP_RE = re.compile(r"\b(4\d{4})\b")  # all Franklin County ZIPs start with 43
_PARCEL_RE = re.compile(r"\d{3}-\d{6}-\d{2}")


@dataclass
class Report:
    url: str
    report_type: str
    period_start: date | None = None
    period_end: date | None = None
    published_on: date | None = None
    reported_count: int | None = None
    reported_avg: float | None = None
    reported_median: float | None = None
    sales: list[dict] = field(default_factory=list)


# ---------- parsing ----------

def _money(s: str) -> int | None:
    # Remove currency formatting and convert the remaining numeric value to an integer dollar amount.
    digits = re.sub(r"[^\d.]", "", s or "")
    return int(float(digits)) if digits else None


def _date(s: str) -> date | None:
    # Accept a few common U.S. date formats and normalize them to Python date objects.
    s = (s or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _month_day(md: str, year: int) -> date:
    # Parse a month-day string like "January 1" into a real date using the given year.
    # "Sept." (AP style) isn't a strptime abbreviation; \b keeps "September" intact.
    md = re.sub(r"^Sept\b", "Sep", md.replace(".", ""))
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(f"{md} {year}", fmt).date()
        except ValueError:
            pass
    raise ValueError(md)


def _parse_period(text: str, year_hint: date | None = None) -> tuple[date | None, date | None]:
    # Extract the report's sale week range from the full page text, including edge cases where
    # the county's date range crosses New Year's or uses a slightly inconsistent wording.
    # year_hint (the publish date) supplies the year when the page omits it.
    m = _PERIOD_RE.search(text)
    if m:
        s_md, s_year, e_md, e_year = m.groups()
    elif year_hint and (m := _PERIOD_NOYEAR_RE.search(text)):
        s_md, e_month, e_day = m.groups()
        e_md = f"{(e_month or s_md.rsplit(' ', 1)[0]).strip()} {e_day}"
        s_year, e_year = None, str(year_hint.year)
    else:
        return None, None
    try:
        end = _month_day(e_md, int(e_year))
        start = _month_day(s_md, int(s_year or e_year))
    except ValueError:
        # An unrecognized month name shouldn't sink the report; its sales still load.
        log.warning("unparseable report period: %r", m.group(0))
        return None, None
    if year_hint and end > year_hint:  # yearless week ending after its publish date: Dec, published Jan
        start, end = (start.replace(year=start.year - 1), end.replace(year=end.year - 1))
    if start > end:  # Dec 26 through Jan 1 -> start is prior year; also fixes county typos
        start = _month_day(s_md, int(e_year) - 1) if start.month > end.month else end - timedelta(days=6)
    return start, end


def _header_map(headers: list[str]) -> dict[str, int]:
    # Map the relevant table columns to canonical names so parsing is not brittle to column order.
    out = {}
    for i, h in enumerate(h.lower() for h in headers):
        if "parcel" in h:
            out["parcel"] = i
        elif "address" in h:
            out["address"] = i
        elif "date" in h:
            out["date"] = i
        elif "price" in h or "amount" in h:
            out["price"] = i
    return out


def _table_zip(table) -> str | None:
    # Find the ZIP code for a table from the caption or nearby heading text, since the table itself
    # may not include an explicit ZIP field.
    cap = table.find("caption")
    if cap and (m := _ZIP_RE.search(cap.get_text(" "))):
        return m.group(1)
    # The ZIP heading precedes the table; the "Residential home sales in ZIP Code X" line may follow it.
    for sib in (table.find_previous(["h2", "h3", "h4", "strong", "p"]),
                table.find_next(["p", "figcaption", "div"])):
        if sib and (m := _ZIP_RE.fullmatch(sib.get_text(strip=True)) or
                    re.search(r"ZIP Code\s+(4\d{4})", sib.get_text(" "))):
            return m.group(1)
    return None


def parse_report(html: str, url: str) -> Report:
    # Parse the HTML report into a normalized Report object, capturing metadata and each sale row.
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.get_text(" ") if soup.title else "") + " " + " ".join(
        m.get("content", "") for m in soup.find_all("meta", attrs={"name": "description"}))
    report_type = "commercial" if "commercial" in title.lower() else "residential"
    text = soup.get_text(" ", strip=True)

    rep = Report(url=url, report_type=report_type)
    if m := _PUBLISHED_RE.search(text):
        rep.published_on = datetime.strptime(m.group(1), "%d %B %Y").date()
    rep.period_start, rep.period_end = _parse_period(title + " " + text, rep.published_on)

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        hl = " ".join(headers).lower()

        if "number of sales" in hl and len(rows) > 1:  # county snapshot
            # The summary table gives the county's reported totals and averages, which we keep for
            # validation and downstream reporting.
            vals = [c.get_text(strip=True) for c in rows[1].find_all(["td", "th"])]
            # Header and value rows can differ in length on odd pages; extra cells are ignored.
            cols = {h.lower(): v for h, v in zip(headers, vals, strict=False)}
            rep.reported_count = _money(next((v for k, v in cols.items() if "number" in k), ""))
            rep.reported_avg = _money(next((v for k, v in cols.items() if "average" in k), ""))
            rep.reported_median = _money(next((v for k, v in cols.items() if "median" in k), ""))
            continue

        hm = _header_map(headers)
        if not {"parcel", "date", "price"} <= hm.keys():
            continue
        zip_code = _table_zip(table)
        for tr in rows[1:]:
            # Each remaining table row is a single closed-sale record; we keep only rows where the
            # parcel, sale date, and price all parse successfully.
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) <= max(hm.values()):
                continue
            pm = _PARCEL_RE.search(cells[hm["parcel"]])
            sd, sp = _date(cells[hm["date"]]), _money(cells[hm["price"]])
            if not (pm and sd and sp is not None):
                log.warning("skip unparseable row in %s: %s", url, cells)
                continue
            rep.sales.append({
                "parcel_id": pm.group(0),
                "sale_date": sd.isoformat(),
                "sale_price": sp,
                "site_address": cells[hm["address"]] if "address" in hm else None,
                "zip": zip_code,
            })
    return rep


# ---------- discovery ----------

def _slug_date(url: str) -> date:
    return datetime.strptime(re.search(r"/(\d{8})-", url).group(1), "%Y%m%d").date()


def discover(report_type: str, since: date, max_misses: int = 4) -> list[str]:
    """Report URLs: the listing's first page, then slug guessing for older weeks.

    The listing shows only the newest 10 reports; its paging is an ASP.NET postback, so a
    &page= parameter is ignored. Older weeks are found by guessing slugs week by week until
    `since`, or until `max_misses` weeks in a row have no page (the county appears to keep ~30 weeks).
    """
    # Listing can mix categories if the filter is ignored; the slug says which type a page is.
    tag = "WCSR|Commercial" if report_type == "commercial" else "WHSR|Residential|Home"
    urls: set[str] = set()
    try:
        r = http.get(LISTING[report_type])
        if r.status_code == 200:
            for a in BeautifulSoup(r.text, "lxml").find_all("a", href=True):
                href = urljoin(BASE, a["href"])
                if re.search(r"/News-articles/\d{8}-", href) and re.search(tag, href, re.I):
                    urls.add(href)
        else:
            log.warning("listing returned HTTP %s; using slug guessing only", r.status_code)
    except (http.RobotsDisallowed, requests.RequestException) as e:
        log.warning("listing unavailable (%s); using slug guessing only", e)

    before = min((_slug_date(u) for u in urls), default=None)
    urls |= set(_guess(report_type, since, before, max_misses))
    return sorted(u for u in urls if _slug_date(u) >= since)


def _guess(report_type: str, since: date, before: date | None = None,
           max_misses: int = 4) -> list[str]:
    # Try likely slugs for each Sunday older than `before` (default: this week), stopping at
    # `since` or after `max_misses` consecutive weeks with no page.
    out = []
    if before:
        d = before - timedelta(days=7 + (before.weekday() + 1) % 7)
    else:
        d = date.today() - timedelta(days=(date.today().weekday() + 1) % 7)  # back to Sunday
    misses = 0
    while d >= since and misses < max_misses:
        for pat in SLUG_GUESSES[report_type]:
            # Publication sometimes slips a day; try Sun and Sat/Mon.
            for shift in (0, -1, 1):
                url = f"{BASE}/News-articles/{pat.format(d=(d + timedelta(days=shift)).strftime('%Y%m%d'))}"
                try:
                    ok = http.get(url).status_code == 200
                except (requests.RequestException, http.RobotsDisallowed) as e:
                    log.error("site unreachable (%s); aborting discovery", e)
                    return out
                if ok:
                    out.append(url)
                    break
            else:
                continue
            break
        else:
            misses += 1
            d -= timedelta(days=7)
            continue
        misses = 0
        d -= timedelta(days=7)
    if misses >= max_misses:
        log.info("%s: no page for %s weeks in a row before %s; stopping", report_type, misses,
                 d + timedelta(days=7 * (misses + 1)))
    return out


# ---------- load ----------

def load(con, rep: Report) -> int:
    # Insert or update the weekly report summary and then load each parsed sale row into the
    # auditor database tables. Returns how many sales were new (re-runs insert nothing).
    db.upsert_report(con, {
        "report_url": rep.url, "county": "Franklin", "report_type": rep.report_type,
        "period_start": rep.period_start, "period_end": rep.period_end,
        "published_on": rep.published_on, "reported_count": rep.reported_count,
        "reported_median": rep.reported_median, "reported_avg": rep.reported_avg,
        "parsed_rows": len(rep.sales)})
    n = db.insert_new_sales(con, [{**s, "county": "Franklin", "report_type": rep.report_type,
                                   "report_url": rep.url} for s in rep.sales])
    con.commit()
    if rep.reported_count is not None and rep.reported_count != len(rep.sales):
        log.warning("count mismatch %s: county says %s, parsed %s",
                    rep.url, rep.reported_count, len(rep.sales))
    return n


def run(con, since: date, report_types=("residential",), refetch=False) -> dict:
    # Execute the full Franklin County weekly pipeline: discover URLs, fetch each report, parse sales,
    # and load them into SQL Server while tracking simple stats about what was new or skipped.
    # Skip a report only if it is loaded AND its raw page is saved, so reports loaded before
    # raw_page existed get fetched once more to capture their HTML.
    done = {r[0] for r in con.execute(
        "SELECT report_url FROM auditor_report a WHERE EXISTS "
        "(SELECT 1 FROM raw_page p WHERE p.url = a.report_url)")}
    stats = {"reports": 0, "new_rows": 0, "skipped": 0}
    for rt in report_types:
        for url in discover(rt, since):
            if url in done and not refetch:
                stats["skipped"] += 1
                continue
            try:
                r = http.get(url)
            except (requests.RequestException, http.RobotsDisallowed) as e:
                log.warning("fetch failed %s: %s", url, e)
                stats.setdefault("failed", 0)
                stats["failed"] += 1
                continue
            if r.status_code != 200:
                log.warning("HTTP %s for %s", r.status_code, url)
                stats.setdefault("failed", 0)
                stats["failed"] += 1
                continue
            # Save the page before parsing, so a parser crash still keeps the raw HTML.
            db.save_raw(con, url, r.text, r.status_code)
            con.commit()
            rep = parse_report(r.text, url)
            stats["new_rows"] += load(con, rep)
            stats["reports"] += 1
            log.info("%s: %s rows (%s to %s)", url, len(rep.sales), rep.period_start, rep.period_end)
    return stats


def run_problems(con, stats: dict, today: date | None = None, max_age_days: int = 14) -> list[str]:
    """Why a run should count as failed, even though it finished. Empty if it looks healthy."""
    problems = []
    if stats.get("failed"):
        problems.append(f"{stats['failed']} report pages couldn't be fetched")
    if not stats["reports"] and not stats["skipped"]:
        problems.append("discovery found no reports")
    newest = con.execute("SELECT MAX(period_end) FROM auditor_report WHERE county = 'Franklin'").fetchone()[0]
    if newest is None or ((today or date.today()) - newest).days > max_age_days:
        problems.append(f"newest Franklin week ended {newest}, more than {max_age_days} days ago")
    return problems


def load_url(con, url: str) -> int:
    """Fetch one report page by URL, save it, and load it. Returns how many sales were new.

    For a report discovery can't find. Re-running it is safe.
    """
    if not url.startswith(BASE + "/News-articles/"):
        raise ValueError(f"Not a Franklin County report URL: {url}")
    r = http.get(url)
    r.raise_for_status()
    db.save_raw(con, url, r.text, r.status_code)
    con.commit()
    rep = parse_report(r.text, url)
    log.info("%s: %s rows (%s to %s)", url, len(rep.sales), rep.period_start, rep.period_end)
    return load(con, rep)


def reparse(con) -> dict:
    """Re-parse the latest saved copy of every Franklin report page and load it.

    Use after a parser fix. Adds sales the old parser missed and refreshes each report's
    summary row; sales already stored are not changed or removed.
    """
    stats = {"reports": 0, "new_rows": 0}
    pages = con.execute(
        "SELECT url, content FROM (SELECT url, content, ROW_NUMBER() OVER "
        "(PARTITION BY url ORDER BY fetched_at DESC, id DESC) AS rn FROM raw_page "
        "WHERE http_status = 200 AND url LIKE ?) x WHERE rn = 1 ORDER BY url",
        BASE + "/%").fetchall()
    for url, content in pages:
        stats["new_rows"] += load(con, parse_report(content, url))
        stats["reports"] += 1
    return stats
