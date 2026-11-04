import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

from pipeline import auditor, backup, county_file, db, export, http, redfin, zillow

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
    for t in ("auditor_sale", "auditor_report", "redfin_load_log", "raw_page", "zillow_zhvi",
              "zillow_load_log"):
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
    # Older pages omit the year; it comes from the publish date (incl. a December week published in Jan).
    pub = date(2026, 4, 12)
    assert auditor._parse_period("for the week of Apr. 3\u20139.", pub) == (
        date(2026, 4, 3), date(2026, 4, 9))
    assert auditor._parse_period("for the past week (April 10 - April 16), as", date(2026, 4, 19)) == (
        date(2026, 4, 10), date(2026, 4, 16))
    assert auditor._parse_period("week of Dec. 26 through Jan. 1.", date(2026, 1, 4)) == (
        date(2025, 12, 26), date(2026, 1, 1))
    assert auditor._parse_period("week of Apr. 3\u20139.") == (None, None)  # no year, no hint
    assert auditor._parse_period("for the week of April 17 through 23, 2026.", date(2026, 4, 26)) == (
        date(2026, 4, 17), date(2026, 4, 23))
    assert auditor._date("04-03-2026") == date(2026, 4, 3)  # dashed dates on older pages
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
    with pytest.raises(ValueError) as e:
        county_file.parse(bad)
    msg = str(e.value)
    assert "sale_date" in msg and "sale_price" in msg  # names every missing field
    assert "'parcel'" in msg and "'amount_due'" in msg  # lists the file's headers


def test_redfin_keeps_columbus_metro_and_three_counties(con):
    n = redfin.load(con, file=str(FX / "redfin_weekly.tsv"))
    assert n == 5
    names = {x[0] for x in con.execute(f"SELECT region_name FROM {redfin.TABLE}")}
    assert names == {"Columbus, OH metro area", "Franklin County, OH", "Delaware County, OH",
                     "Licking County, OH"}


def test_raw_page_dedupes_and_reparse_loads(con):
    html = (FX / "whsr.html").read_text()
    url = auditor.BASE + "/News-articles/20261101-WHSR"
    assert db.save_raw(con, url, html, 200) is True
    assert db.save_raw(con, url, html, 200) is False  # same content: no new row
    assert db.save_raw(con, url, html + "<!-- edited -->", 200) is True  # changed: kept as a revision
    con.commit()
    assert auditor.reparse(con) == {"reports": 1, "new_rows": 6}
    assert auditor.reparse(con) == {"reports": 1, "new_rows": 0}


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


def test_discover_guesses_past_listing_and_stops_after_misses(monkeypatch):
    listing = ('<a href="/News-articles/20261101-WHSR">a</a>'
               '<a href="/News-articles/20261025-WHSR">b</a>'
               '<a href="/News-articles/20261025-WCSR">commercial, wrong type</a>')
    live = {"20261018-WHSR", "20261010-WHSR"}  # second one published a day early (Saturday)
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if url == auditor.LISTING["residential"]:
            return _Resp(200, listing)
        return _Resp(200 if url.rsplit("/", 1)[1] in live else 404)

    monkeypatch.setattr(auditor.http, "get", fake_get)
    got = auditor.discover("residential", date(2026, 1, 1), max_misses=2)
    assert [u.rsplit("/", 1)[1] for u in got] == [
        "20261010-WHSR", "20261018-WHSR", "20261025-WHSR", "20261101-WHSR"]
    # Listing once; then two weeks found; then 2 dead weeks x 4 slugs x 3 day shifts, then stop.
    assert not any("page=" in u for u in calls)
    assert len(calls) == 1 + 1 + 2 + 2 * 12


class _HResp:
    def __init__(self, status, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}
        self.ok = status < 400


@pytest.fixture
def fake_net(monkeypatch):
    """Route http's session to a dict of url -> list of responses; record sleeps."""
    routes, sleeps = {}, []
    monkeypatch.setattr(http, "_robots", {})
    monkeypatch.setattr(http, "_last_hit", {})
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    monkeypatch.setattr(http._session, "get", lambda url, **kw: routes[url].pop(0))
    monkeypatch.setattr(http._session, "request", lambda m, url, **kw: routes[url].pop(0))
    return routes, sleeps


def test_http_blocked_robots_means_disallow(fake_net):
    routes, _ = fake_net
    routes["https://a.test/robots.txt"] = [_HResp(403)]
    with pytest.raises(http.RobotsDisallowed):
        http.get("https://a.test/page")
    routes["https://b.test/robots.txt"] = [_HResp(503), _HResp(404)]
    with pytest.raises(http.RobotsDisallowed):  # server error: refuse now...
        http.get("https://b.test/page")
    routes["https://b.test/page"] = [_HResp(200)]
    assert http.get("https://b.test/page").status_code == 200  # ...but retry robots later


def test_http_crawl_delay_and_retry_after(fake_net):
    routes, sleeps = fake_net
    routes["https://c.test/robots.txt"] = [_HResp(200, "User-agent: *\nCrawl-delay: 10\n")]
    routes["https://c.test/p"] = [_HResp(429, headers={"Retry-After": "7"}), _HResp(200)]
    assert http.get("https://c.test/p").status_code == 200
    assert 7.0 in sleeps                    # honored Retry-After
    assert any(s > 9 for s in sleeps if s != 7.0)  # throttled to Crawl-delay, not 2s


def test_zillow_keeps_three_ohio_counties_and_their_zips(con):
    assert zillow.load(con, "county", file=str(FX / "zillow_county.csv")) == 11  # one blank month
    assert zillow.load(con, "zip", file=str(FX / "zillow_zip.csv")) == 8
    got = {tuple(r) for r in con.execute("SELECT DISTINCT region_type, region_name, county FROM zillow_zhvi")}
    assert got == {("county", "Franklin County", "Franklin"), ("county", "Delaware County", "Delaware"),
                   ("county", "Licking County", "Licking"), ("zip", "43215", "Franklin"),
                   ("zip", "43035", "Delaware")}  # PA/MA Franklin, Cuyahoga, Columbus GA dropped
    r = con.execute("SELECT zhvi, zhvi_prior_year, zhvi_yoy_pct FROM v_zillow_yoy WHERE region_name"
                    " = 'Franklin County' AND month = '2026-10-01'").fetchone()
    assert tuple(r) == (302000.0, 281000.0, 7.5)
    # Reload replaces rather than duplicates; every load records the required attribution.
    assert zillow.load(con, "county", file=str(FX / "zillow_county.csv")) == 11
    assert con.execute("SELECT COUNT(*) FROM zillow_zhvi WHERE region_type = 'county'").fetchone()[0] == 11
    assert {r[0] for r in con.execute("SELECT attribution FROM zillow_load_log")} == {zillow.ATTRIBUTION}


def test_zillow_skips_download_when_file_unchanged(con, monkeypatch):
    lm = "Fri, 16 Oct 2026 01:51:26 GMT"
    body = (FX / "zillow_county.csv").read_bytes()
    gets = []

    class R:
        def __init__(self, content=b""):
            self.headers, self.content = {"Last-Modified": lm}, content
        def raise_for_status(self):
            pass

    monkeypatch.setattr(zillow.http, "head", lambda url, **kw: R())
    monkeypatch.setattr(zillow.http, "get", lambda url, **kw: gets.append(url) or R(body))
    assert zillow.load(con, "county") == 11
    assert zillow.load(con, "county") is None  # same Last-Modified: no second download
    assert len(gets) == 1


def test_redfin_gzip_read_in_chunks(con, monkeypatch, tmp_path):
    gz = tmp_path / "weekly.tsv000"  # gzipped without a .gz name, like Redfin's S3 files
    import gzip
    gz.write_bytes(gzip.compress((FX / "redfin_weekly.tsv").read_bytes()))
    monkeypatch.setattr(redfin, "CHUNK_ROWS", 3)  # 8 rows -> 3 chunks
    assert redfin.load(con, file=str(gz)) == 5
    price = con.execute(f"SELECT median_sale_price FROM {redfin.TABLE} "
                        "WHERE region_name = 'Franklin County, OH'").fetchone()[0]
    assert price == 330000  # text read per chunk, converted back to a number


def test_backup_prune_keeps_newest_of_that_database_only(tmp_path):
    for stamp in ("20261101_070000", "20261102_070000", "20261103_070000"):
        (tmp_path / f"columbus_housing_{stamp}.bak").touch()
    other = tmp_path / "columbus_housing_test_20260101_070000.bak"
    other.touch()
    note = tmp_path / "notes.txt"
    note.touch()
    removed = backup.prune(tmp_path, "columbus_housing", keep=2)
    assert [f.name for f in removed if "20261101" in f.name] == ["columbus_housing_20261101_070000.bak"]
    assert (tmp_path / "columbus_housing_20261103_070000.bak").exists()
    assert (tmp_path / "columbus_housing_20261102_070000.bak").exists()
    assert note.exists()
    assert other.exists()


def test_export_only_sends_new_rows(con, tmp_path):
    con.execute("INSERT INTO auditor_report (report_url, report_type) VALUES ('r','residential')")
    insert = ("INSERT INTO auditor_sale (parcel_id, sale_date, sale_price, report_type, report_url,"
              " loaded_at) VALUES (?, '2026-10-26', ?, 'residential', 'r', ?)")
    con.execute(insert, "A", 100000, "2026-11-01T08:00:00")
    con.execute(insert, "B", 200000, "2026-11-02T08:00:00")
    con.commit()

    path, high, rows = export.export_new(con, "auditor_sale", None, tmp_path)
    assert (rows, high, path.name) == (2, "2026-11-02T08:00:00", "auditor_sale_20261102_080000.csv")
    header = path.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert "source_loaded_at" in header and "loaded_at" not in header  # bronze adds its own loaded_at

    assert export.export_new(con, "auditor_sale", high, tmp_path) == (None, high, 0)  # nothing new

    con.execute(insert, "C", 300000, "2026-11-03T08:00:00")
    con.commit()
    path, high, rows = export.export_new(con, "auditor_sale", high, tmp_path)
    assert (rows, high) == (1, "2026-11-03T08:00:00")
    assert ",C," not in path.read_text(encoding="utf-8").splitlines()[0]
    assert "C" in path.read_text(encoding="utf-8").splitlines()[1].split(",")

    with pytest.raises(KeyError):
        export.export_new(con, "raw_page; DROP TABLE x", None, tmp_path)


def test_load_url_saves_page_and_loads_once(con, monkeypatch):
    html = (FX / "whsr.html").read_text()
    url = auditor.BASE + "/News-articles/20260510-Weekly-Home-Sales-Report"

    class R:
        status_code, text = 200, html

        def raise_for_status(self):
            pass

    monkeypatch.setattr(auditor.http, "get", lambda u, **kw: R())
    assert auditor.load_url(con, url) == 6
    assert auditor.load_url(con, url) == 0  # safe to repeat
    assert con.execute("SELECT COUNT(*) FROM raw_page WHERE url = ?", url).fetchone()[0] == 1
    with pytest.raises(ValueError, match="Not a Franklin"):
        auditor.load_url(con, "https://example.com/News-articles/20260510-WHSR")


def _run_pipeline_module():
    spec = importlib.util.spec_from_file_location(
        "run_pipeline", Path(__file__).parent.parent / "databricks" / "run_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("final, expected", [("COMPLETED", 0), ("FAILED", 1)])
def test_run_pipeline_reports_how_a_restart_ended(monkeypatch, final, expected):
    rp = _run_pipeline_module()
    old = {"update_id": "old", "state": "COMPLETED", "cause": "API_CALL"}
    stopped = {"update_id": "a", "state": "CANCELED", "cause": "API_CALL"}
    restart = {"update_id": "b", "state": "RUNNING", "cause": "SCHEMA_CHANGE"}
    done = {"update_id": "b", "state": final, "cause": "SCHEMA_CHANGE"}
    # Newest first. The stopped update is settled for two polls before the restart shows up.
    seen = iter([[old], [stopped, old], [stopped, old], [restart, stopped, old],
                 [done, stopped, old], [done, stopped, old], [done, stopped, old]])

    class Done:
        returncode = 1

    monkeypatch.setattr(rp.shutil, "which", lambda name: "databricks")
    monkeypatch.setattr(rp, "_json", lambda *a: [{"name": rp.NAMES["dev"], "pipeline_id": "p"}])
    monkeypatch.setattr(rp, "_updates", lambda pipeline_id: next(seen))
    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(rp.time, "sleep", lambda seconds: None)
    assert rp.run("dev") == expected


def test_run_pipeline_ignores_a_finished_update_from_before_this_run(monkeypatch):
    rp = _run_pipeline_module()
    old = {"update_id": "old", "state": "COMPLETED", "cause": "API_CALL"}

    class Done:
        returncode = 1

    monkeypatch.setattr(rp.shutil, "which", lambda name: "databricks")
    monkeypatch.setattr(rp, "_json", lambda *a: [{"name": rp.NAMES["dev"], "pipeline_id": "p"}])
    monkeypatch.setattr(rp, "_updates", lambda pipeline_id: [old])
    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(rp.time, "sleep", lambda seconds: None)
    assert rp.run("dev") == 1  # a failed start must not borrow an earlier update's success


def test_run_problems_flags_runs_that_look_finished_but_failed(con):
    today = date(2026, 11, 9)
    healthy = {"reports": 1, "new_rows": 300, "skipped": 8}
    assert "older" not in " ".join(auditor.run_problems(con, healthy, today))
    assert auditor.run_problems(con, healthy, today)  # empty table: nothing is fresh

    con.execute("INSERT INTO auditor_report (report_url, report_type, period_end) "
                "VALUES ('r', 'residential', '2026-11-05')")
    assert auditor.run_problems(con, healthy, today) == []
    assert auditor.run_problems(con, {"reports": 0, "new_rows": 0, "skipped": 9}, today) == []  # nothing new
    assert "discovery found no reports" in auditor.run_problems(
        con, {"reports": 0, "new_rows": 0, "skipped": 0}, today)
    assert any("couldn't be fetched" in x for x in auditor.run_problems(con, {**healthy, "failed": 2}, today))
    assert any("days ago" in x for x in auditor.run_problems(con, healthy, date(2026, 12, 1)))
