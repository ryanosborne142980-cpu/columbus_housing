from datetime import date, timedelta
from pathlib import Path

import pytest

from pipeline import auditor, county_file, db, redfin

FX = Path(__file__).parent / "fixtures"


TEST_DB = "columbus_housing_test"


@pytest.fixture(scope="session")
def _con():
    con = db.connect(TEST_DB)
    yield con
    con.close()


@pytest.fixture
def con(_con):
    # Empty every table so each test starts clean.
    _con.execute(f"DROP TABLE IF EXISTS {redfin.TABLE}")
    for t in ("auditor_sale", "auditor_report", "redfin_load_log"):
        _con.execute(f"DELETE FROM {t}")
    _con.commit()
    return _con


def rows(con, sql, *params):
    return [tuple(r) for r in con.execute(sql, *params).fetchall()]


def ins(con, sql, data):
    con.cursor().executemany(sql, data)


def test_parse_residential():
    rep = auditor.parse_report((FX / "whsr.html").read_text(), "u/20261101-WHSR")
    assert rep.report_type == "residential"
    assert (rep.period_start, rep.period_end) == (date(2026, 10, 23), date(2026, 10, 29))
    assert rep.published_on == date(2026, 11, 1)
    assert (rep.reported_count, rep.reported_median) == (6, 300000)
    assert len(rep.sales) == 6
    assert {s["zip"] for s in rep.sales} == {"43004", "43229"}
    first = rep.sales[0]
    assert first == {"parcel_id": "170-002584-00", "sale_date": "2026-10-28", "sale_price": 890000,
                     "site_address": "7703 W HAVENS CT", "zip": "43004"}


def test_parse_commercial_caption_and_year_wrap():
    rep = auditor.parse_report((FX / "wcsr.html").read_text(), "u/20260104-WCSR")
    assert rep.report_type == "commercial"
    assert (rep.period_start, rep.period_end) == (date(2025, 12, 26), date(2026, 1, 1))
    assert [s["zip"] for s in rep.sales] == ["43212", "43212"]


def test_parse_period_month_abbreviations():
    assert auditor._parse_period("week of Sept. 19 through Sept. 25, 2026") == (
        date(2026, 9, 19), date(2026, 9, 25))
    assert auditor._parse_period("week of September 19 through Sep. 25, 2026") == (
        date(2026, 9, 19), date(2026, 9, 25))
    # Unknown month name: no period, no exception.
    assert auditor._parse_period("week of Smarch 1 through Smarch 7, 2026") == (None, None)


def test_load_idempotent_and_validation(con):
    rep = auditor.parse_report((FX / "whsr.html").read_text(), "u/20261101-WHSR")
    assert auditor.load(con, rep) == 6
    assert auditor.load(con, rep) == 0  # re-run inserts nothing
    assert con.execute("SELECT diff FROM v_report_validation").fetchone()[0] == 0


def test_clean_view_drops_nominal_and_collapses_multiparcel(con):
    con.execute("INSERT INTO auditor_report (report_url, report_type) VALUES ('r','residential')")
    data = [("A-1", "2026-10-26", 229500, "1631 ROXBURY RD", "43212"),
            ("A-2", "2026-10-26", 229500, "1631 ROXBURY RD", "43212"),  # same deed, 2 parcels
            ("B-1", "2026-10-26", 10, "1 QUITCLAIM LN", "43212"),        # nominal
            ("C-1", "2026-10-27", 300000, "2 MAIN ST", "43212")]
    ins(con, "INSERT INTO auditor_sale (parcel_id, sale_date, sale_price, site_address, zip,"
             " report_type, report_url) VALUES (?,?,?,?,?,'residential','r')", data)
    got = rows(con, "SELECT sale_price, parcel_count FROM v_sale_clean ORDER BY sale_price")
    assert got == [(229500, 2), (300000, 1)]
    wk = rows(con, "SELECT week_start, sales, median_price FROM v_county_week")[0]
    assert wk == (date(2026, 10, 26), 2, 264750.0)  # Monday start; even-n median averages middle two


def test_rolling4_pools_sales_and_computes_yoy(con):
    con.execute("INSERT INTO auditor_report (report_url, report_type) VALUES ('r','residential')")
    base = date(2026, 10, 26)  # Monday
    data, i = [], 0
    for yr_back, price in ((0, 300000), (1, 250000)):
        for w in range(4):
            d = base - timedelta(days=7 * w + 364 * yr_back)
            for k in range(3):
                i += 1
                data.append((f"P{i}", d.isoformat(), price + k * 1000, f"{i} ST", "43004"))
    ins(con, "INSERT INTO auditor_sale (parcel_id, sale_date, sale_price, site_address, zip,"
             " report_type, report_url) VALUES (?,?,?,?,?,'residential','r')", data)
    r = con.execute("SELECT sales_4wk, median_4wk, median_4wk_prior_year, median_yoy_pct "
                    "FROM v_county_rolling4 WHERE week_start = ?", base).fetchone()
    assert tuple(r) == (12, 301000.0, 251000.0, 19.9)


def test_rolling4_keeps_counties_separate(con):
    con.execute("INSERT INTO auditor_report (report_url, report_type) VALUES ('r','residential')")
    data = [("Franklin", "F1", 300000), ("Franklin", "F2", 310000),
            ("Delaware", "D1", 500000), ("Delaware", "F1", 520000)]  # parcel IDs may repeat across counties
    ins(con, "INSERT INTO auditor_sale (county, parcel_id, sale_date, sale_price, site_address,"
             " zip, report_type, report_url) VALUES (?,?,'2026-10-27',?,?,'43035','residential','r')",
        [(c, p, price, f"{p} {c}") for c, p, price in data])
    got = rows(con, "SELECT county, sales_4wk, median_4wk FROM v_county_rolling4 ORDER BY county")
    assert got == [("Delaware", 2, 510000.0), ("Franklin", 2, 305000.0)]


def test_county_file_maps_columns_and_filters_residential(con):
    f = str(FX / "delaware_sales.csv")
    assert county_file.load(con, "Delaware", f) == 2  # commercial row and dateless row dropped
    assert county_file.load(con, "Delaware", f) == 0  # re-run inserts nothing
    got = rows(con, "SELECT county, parcel_id, sale_date, sale_price, zip FROM auditor_sale"
                    " ORDER BY sale_date")
    assert got == [("Delaware", "41923001005000", date(2026, 10, 27), 612000, "43035"),
                   ("Delaware", "41923001006000", date(2026, 10, 28), 455500, "43035")]
    rep = rows(con, "SELECT county, period_start, period_end, parsed_rows FROM auditor_report")[0]
    assert rep == ("Delaware", date(2026, 10, 27), date(2026, 10, 28), 2)


def test_county_file_missing_columns_lists_headers(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Parcel,Amount Due\n1,2\n")
    with pytest.raises(ValueError, match="sale_date"):
        county_file.parse(bad)


def test_redfin_keeps_columbus_metro_and_three_counties(con):
    n = redfin.load(con, file=str(FX / "redfin_weekly.tsv"))
    assert n == 5
    names = {x[0] for x in con.execute(f"SELECT region_name FROM {redfin.TABLE}")}
    assert names == {"Columbus, OH metro area", "Franklin County, OH", "Delaware County, OH",
                     "Licking County, OH"}
