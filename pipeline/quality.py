"""Data quality rules, run after each load (python run.py check).

A "fail" means the data is wrong or incomplete: the check exits 1 and the weekly job doesn't land
anything in Databricks. A "warn" may be a real sale or a county quirk, so it's printed for review and
blocks nothing. The rules are checks rather than table constraints because sql/schema.sql doesn't
alter existing tables. Thresholds come from the first 59 reports, so expect to adjust them.

Rules for Databricks are in databricks/reconcile.py, and the guard against a cut-off Zillow file is
in pipeline/zillow.py, because both have to run at a different point from this check.
"""
from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass

from . import redfin
from .auditor import _PARCEL_RE

FAIL = "fail"
WARN = "warn"
PRINT_ROWS = 5  # a rule can match many rows; show enough to start looking
VOLUME_WEEKS = 8
VOLUME_MIN_RATIO = 0.5
REDFIN_REGIONS = ("Franklin County, OH", "Delaware County, OH", "Licking County, OH")
REDFIN_METRO = "Columbus, OH"

# Checked exceptions, by rule and the first column of the row: {rule: {key: what was found}}.
_REPORTS = "https://auditor.franklincountyohio.gov/News-articles/"
KNOWN = {
    "published_count_matches": {
        _REPORTS + "20260913-WHSR": "The page lists 336 parcels; its summary says 337.",
    },
    "franklin_zip_prefix": {
        "053-001136-00": "The county's page files this sale under ZIP 46026. Others in this parcel "
                         "range are mostly 43026, so it's probably their typo; left as published.",
    },
}


def _parsed_matches_page(con) -> list[tuple]:
    rows = con.execute(
        "SELECT r.report_url, r.parsed_rows, (SELECT TOP 1 p.content FROM raw_page p "
        "WHERE p.url = r.report_url ORDER BY p.fetched_at DESC, p.id DESC) FROM auditor_report r "
        "WHERE r.report_url NOT LIKE 'file:%'").fetchall()
    found = [(url, parsed, len(_PARCEL_RE.findall(page))) for url, parsed, page in rows if page]
    return [row for row in found if row[1] != row[2]]


def _weekly_volume_dip(con) -> list[tuple]:
    rows = con.execute(
        f"SELECT TOP {VOLUME_WEEKS + 1} report_url, parsed_rows FROM auditor_report "
        "WHERE county = 'Franklin' AND report_type = 'residential' ORDER BY published_on DESC").fetchall()
    if len(rows) < 5:
        return []
    usual = statistics.median(r[1] for r in rows[1:])
    return [(rows[0][0], rows[0][1], usual)] if rows[0][1] < VOLUME_MIN_RATIO * usual else []


def _redfin_columns(con) -> list[tuple]:
    return [tuple(r) for r in con.execute(
        "SELECT c.name, t.name FROM sys.columns c JOIN sys.types t ON t.user_type_id = c.user_type_id "
        "WHERE c.object_id = OBJECT_ID(?)", redfin.TABLE).fetchall()]


def _redfin_regions(con) -> list[tuple]:
    columns = {name for name, _ in _redfin_columns(con)}
    if not columns:  # not loaded yet
        return []
    region = next((c for c in ("region_name", "region") if c in columns), None)
    if not region:
        return [("no region column", sorted(columns)[:10])]
    names = {r[0] for r in con.execute(f"SELECT DISTINCT [{region}] FROM {redfin.TABLE}").fetchall()}
    metro = {n for n in names if n and n.startswith(REDFIN_METRO)}
    missing = [("missing", n) for n in REDFIN_REGIONS if n not in names]
    if not metro:
        missing.append(("missing", REDFIN_METRO))
    return missing + [("unexpected", n) for n in sorted(names - metro - set(REDFIN_REGIONS), key=str)]


def _redfin_dates(con) -> list[tuple]:
    found = []
    for name, sql_type in _redfin_columns(con):
        if sql_type == "date":
            n = con.execute(
                f"SELECT COUNT(*) FROM {redfin.TABLE} WHERE [{name}] < '2000-01-01'").fetchone()[0]
            if n:
                found.append((name, n))
    return found


@dataclass(frozen=True)
class Rule:
    name: str
    severity: str
    why: str
    source: str | Callable  # a query returning one row per violation, or a function that does


RULES = [
    Rule("sale_type_matches_report", FAIL, "A sale's type differs from its report's.",
         "SELECT a.parcel_id, a.report_type, r.report_type FROM auditor_sale a "
         "JOIN auditor_report r ON r.report_url = a.report_url WHERE a.report_type <> r.report_type"),
    Rule("sale_price_positive", FAIL, "A sale has no positive price.",
         "SELECT parcel_id, sale_date, sale_price FROM auditor_sale WHERE sale_price <= 0"),
    Rule("sale_date_not_future", FAIL, "A sale is dated in the future.",
         "SELECT parcel_id, sale_date FROM auditor_sale WHERE sale_date > CAST(GETDATE() AS DATE)"),
    Rule("sale_date_near_report_week", FAIL, "A sale is before its report's week, or over 7 days after it.",
         "SELECT a.parcel_id, a.sale_date, r.period_start, r.period_end FROM auditor_sale a "
         "JOIN auditor_report r ON r.report_url = a.report_url "
         "WHERE a.sale_date < r.period_start OR a.sale_date > DATEADD(day, 7, r.period_end)"),
    Rule("allowed_values", FAIL, "A county or report type isn't one the pipeline knows.",
         "SELECT report_url, county, report_type FROM auditor_report "
         "WHERE county NOT IN ('Franklin', 'Delaware', 'Licking') "
         "OR report_type NOT IN ('residential', 'commercial') "
         "UNION ALL SELECT parcel_id, county, report_type FROM auditor_sale "
         "WHERE county NOT IN ('Franklin', 'Delaware', 'Licking') "
         "OR report_type NOT IN ('residential', 'commercial')"),
    Rule("franklin_parcel_format", FAIL, "A Franklin parcel ID isn't in the form 123-456789-00.",
         "SELECT parcel_id, sale_date FROM auditor_sale WHERE county = 'Franklin' AND parcel_id NOT LIKE "
         "'[0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9]'"),
    Rule("report_has_sales", FAIL, "A report loaded no sales; the page's format may have changed.",
         "SELECT report_url, parsed_rows FROM auditor_report WHERE COALESCE(parsed_rows, 0) = 0"),
    Rule("published_count_matches", FAIL, "Parsed rows differ from the county's published count.",
         "SELECT report_url, parsed_rows, reported_count FROM auditor_report "
         "WHERE reported_count IS NOT NULL AND parsed_rows <> reported_count"),
    Rule("parsed_matches_page", FAIL, "Parsed rows differ from the parcel IDs in the saved page.",
         _parsed_matches_page),
    Rule("report_period_valid", FAIL, "A report's week is blank or runs backwards.",
         "SELECT report_url, period_start, period_end FROM auditor_report "
         "WHERE period_start IS NULL OR period_end IS NULL OR period_start > period_end"),
    Rule("franklin_raw_page_saved", FAIL, "A Franklin report has no saved page, so it can't be re-parsed.",
         "SELECT r.report_url FROM auditor_report r WHERE r.report_url NOT LIKE 'file:%' "
         "AND NOT EXISTS (SELECT 1 FROM raw_page p WHERE p.url = r.report_url)"),
    Rule("zillow_counties_present", FAIL, "Zillow is missing a county.",
         "SELECT v.name FROM (VALUES ('Franklin County'), ('Delaware County'), ('Licking County')) v(name) "
         "WHERE NOT EXISTS (SELECT 1 FROM zillow_zhvi z "
         "WHERE z.region_type = 'county' AND z.region_name = v.name)"),
    Rule("zillow_value_positive", FAIL, "A Zillow value isn't positive.",
         "SELECT region_name, month, zhvi FROM zillow_zhvi WHERE zhvi <= 0"),
    Rule("redfin_regions", FAIL, "Redfin doesn't hold exactly the Columbus metro and three counties.",
         _redfin_regions),
    Rule("redfin_dates", FAIL, "A Redfin date column has values before 2000; it may not be a date.",
         _redfin_dates),
    Rule("franklin_zip_prefix", WARN, "A Franklin sale's ZIP doesn't start with 43.",
         "SELECT parcel_id, zip, sale_date FROM auditor_sale WHERE county = 'Franklin' "
         "AND (zip IS NULL OR zip NOT LIKE '43[0-9][0-9][0-9]')"),
    Rule("residential_price_cap", WARN, "A residential sale is over $5M; it may not be a house.",
         "SELECT parcel_id, site_address, sale_date, sale_price FROM auditor_sale "
         "WHERE report_type = 'residential' AND sale_price > 5000000"),
    Rule("report_covers_7_days", WARN, "A report's week isn't 7 days long.",
         "SELECT report_url, period_start, period_end FROM auditor_report WHERE report_url NOT LIKE 'file:%' "
         "AND DATEDIFF(day, period_start, period_end) <> 6"),
    Rule("report_period_unique", WARN, "Two reports give the same week.",
         "SELECT report_type, period_start, period_end, COUNT(*) FROM auditor_report "
         "WHERE report_url NOT LIKE 'file:%' "
         "GROUP BY report_type, period_start, period_end HAVING COUNT(*) > 1"),
    Rule("weekly_cadence", WARN, "Reports aren't 7 days apart, so a week may be missing.",
         "SELECT report_url, previous, published_on FROM (SELECT report_url, published_on, LAG(published_on) "
         "OVER (PARTITION BY report_type ORDER BY published_on) AS previous FROM auditor_report "
         "WHERE county = 'Franklin') t WHERE DATEDIFF(day, previous, published_on) <> 7"),
    Rule("weekly_volume_dip", WARN, "The newest week has under half the usual residential sales.",
         _weekly_volume_dip),
    Rule("zillow_monthly_change", WARN, "A Zillow value moved over 10% in a month.",
         "SELECT region_name, month, zhvi, previous FROM (SELECT region_type, region_name, month, zhvi, "
         "LAG(zhvi) OVER (PARTITION BY region_type, region_name ORDER BY month) AS previous "
         "FROM zillow_zhvi) t "
         "WHERE ABS(zhvi - previous) / NULLIF(previous, 0) > 0.10"),
    Rule("sale_in_report_week", WARN, "A report has sales dated outside its week.",
         "SELECT a.report_url, COUNT(*) FROM auditor_sale a "
         "JOIN auditor_report r ON r.report_url = a.report_url "
         "WHERE a.sale_date NOT BETWEEN r.period_start AND r.period_end GROUP BY a.report_url"),
]


@dataclass(frozen=True)
class Finding:
    rule: Rule
    rows: list[tuple]


def check(con) -> list[Finding]:
    """Run every rule. Returns the rules with violations, leaving out checked exceptions in KNOWN."""
    findings = []
    for rule in RULES:
        if callable(rule.source):
            rows = rule.source(con)
        else:
            rows = [tuple(r) for r in con.execute(rule.source).fetchall()]
        rows = [r for r in rows if str(r[0]) not in KNOWN.get(rule.name, {})]
        if rows:
            findings.append(Finding(rule, rows))
    return findings


def failures(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.rule.severity == FAIL]


def print_report(findings: list[Finding]) -> None:
    for f in sorted(findings, key=lambda f: f.rule.severity):
        print(f"{f.rule.severity.upper()} {f.rule.name}: {len(f.rows)}. {f.rule.why}")
        for row in f.rows[:PRINT_ROWS]:
            print("   ", " | ".join(str(v) for v in row))
        if len(f.rows) > PRINT_ROWS:
            print(f"    ...and {len(f.rows) - PRINT_ROWS} more")
    n_fail = len(failures(findings))
    print(f"check: {len(RULES)} rules, {n_fail} failed, {len(findings) - n_fail} warned")
