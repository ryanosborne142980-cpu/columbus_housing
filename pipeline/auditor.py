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
    "residential": ["{d}-WHSR", "{d}-Residential-Sales-Report", "{d}-Home-Sales"],
    "commercial": ["{d}-WCSR", "{d}-Commercial-Sales"],
}

_PERIOD_RE = re.compile(
    r"(?:week of|from)\s+([A-Z][a-z]+\.?\s+\d{1,2})(?:,?\s+(\d{4}))?\s+(?:through|to|-)\s+"
    r"([A-Z][a-z]+\.?\s+\d{1,2}),?\s+(\d{4})"
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
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
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


def _parse_period(text: str) -> tuple[date | None, date | None]:
    # Extract the report's sale week range from the full page text, including edge cases where
    # the county's date range crosses New Year's or uses a slightly inconsistent wording.
    m = _PERIOD_RE.search(text)
    if not m:
        return None, None
    s_md, s_year, e_md, e_year = m.groups()
    try:
        end = _month_day(e_md, int(e_year))
        start = _month_day(s_md, int(s_year or e_year))
    except ValueError:
        # An unrecognized month name shouldn't sink the report; its sales still load.
        log.warning("unparseable report period: %r", m.group(0))
        return None, None
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
    rep.period_start, rep.period_end = _parse_period(title + " " + text)
    if m := _PUBLISHED_RE.search(text):
        rep.published_on = datetime.strptime(m.group(1), "%d %B %Y").date()

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
            cols = {h.lower(): v for h, v in zip(headers, vals)}
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

def discover(report_type: str, since: date, max_pages: int = 60) -> list[str]:
    """Report URLs from the category listing; falls back to slug guessing per Sunday."""
    # Crawl the county's article listing to find report URLs; if that listing is blocked or noisy,
    # fall back to guessing common slug patterns for each Sunday issue.
    urls: list[str] = []
    try:
        for page in range(1, max_pages + 1):
            r = http.get(f"{LISTING[report_type]}&page={page}")
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, "lxml")
            found = []
            for a in soup.find_all("a", href=True):
                href = urljoin(BASE, a["href"])
                m = re.search(r"/News-articles/(\d{8})-", href)
                if m and href not in urls and href not in found:
                    found.append(href)
            if not found:
                break
            urls.extend(found)
            oldest = min(datetime.strptime(re.search(r"/(\d{8})-", u).group(1), "%Y%m%d").date()
                         for u in found)
            if oldest < since:
                break
    except (http.RobotsDisallowed, requests.RequestException) as e:
        log.warning("listing unavailable (%s); falling back to slug guessing", e)

    if not urls:
        urls = _guess(report_type, since)
    keep = [u for u in urls
            if datetime.strptime(re.search(r"/(\d{8})-", u).group(1), "%Y%m%d").date() >= since]
    # Listing can mix categories if the filter is ignored; the URL slug tells us whether the page is
    # residential or commercial before we return the final set.
    tag = "WCSR|Commercial" if report_type == "commercial" else "WHSR|Residential|Home"
    return sorted({u for u in keep if re.search(tag, u, re.I)})


def _guess(report_type: str, since: date) -> list[str]:
    # Some weeks do not appear in the listing, so try the most likely URL slugs directly and scan back
    # in weekly intervals until we reach the requested cutoff date.
    out, d = [], date.today()
    d -= timedelta(days=(d.weekday() + 1) % 7)  # back to Sunday
    while d >= since:
        for pat in SLUG_GUESSES[report_type]:
            # Publication sometimes slips a day; try Sun and Sat/Mon.
            for shift in (0, -1, 1):
                url = f"{BASE}/News-articles/{pat.format(d=(d + timedelta(days=shift)).strftime('%Y%m%d'))}"
                try:
                    ok = http.get(url).status_code == 200
                except requests.RequestException as e:
                    log.error("site unreachable (%s); aborting discovery", e)
                    return out
                if ok:
                    out.append(url)
                    break
            else:
                continue
            break
        d -= timedelta(days=7)
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
    done = {r[0] for r in con.execute("SELECT report_url FROM auditor_report")}
    stats = {"reports": 0, "new_rows": 0, "skipped": 0}
    for rt in report_types:
        for url in discover(rt, since):
            if url in done and not refetch:
                stats["skipped"] += 1
                continue
            try:
                r = http.get(url)
            except requests.RequestException as e:
                log.warning("fetch failed %s: %s", url, e)
                stats.setdefault("failed", 0)
                stats["failed"] += 1
                continue
            if r.status_code != 200:
                log.warning("HTTP %s for %s", r.status_code, url)
                continue
            rep = parse_report(r.text, url)
            stats["new_rows"] += load(con, rep)
            stats["reports"] += 1
            log.info("%s: %s rows (%s to %s)", url, len(rep.sales), rep.period_start, rep.period_end)
    return stats
