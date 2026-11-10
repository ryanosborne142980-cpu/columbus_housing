"""Exercise the real pipeline code with small sample files, in a separate test schema.

Run from the repo root:  python databricks/drift_test.py

Covers what real data hasn't produced yet: repeat runs, schema drift, repeated versions of a row, a
new Zillow release, and bad rows. Each stage lands files, runs the pipeline and prints PASS or FAIL.
It needs a fresh test target, because Auto Loader remembers files it has seen. Reset with:
  databricks bundle destroy -t test -p columbus
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from run_pipeline import run

CLI = shutil.which("databricks")
if not CLI:
    sys.exit("databricks CLI not on PATH")
HERE = Path(__file__).resolve().parent
PROFILE = ["-p", "columbus"]
S = "workspace.columbus_housing_test."
VOLUME = "dbfs:/Volumes/workspace/columbus_housing_test/raw"
SALE = "county,parcel_id,sale_date,sale_price,site_address,zip,report_type,report_url,source_loaded_at"
REPORT = ("report_url,county,report_type,period_start,period_end,published_on,reported_count,"
          "reported_median,reported_avg,parsed_rows,fetched_at")
ZILLOW = "RegionID,SizeRank,RegionName,RegionType,StateName,State,Metro,StateCodeFIPS,MunicipalCodeFIPS"
results = []
warehouse = None


def cli(*args, cwd=None):
    r = subprocess.run([CLI, *args, *PROFILE], capture_output=True, text=True, encoding="utf-8", cwd=cwd)
    if r.returncode:
        sys.exit(f"{' '.join(args)} failed:\n{r.stderr[-800:]}")
    return r


def land(folder, name, lines):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cli("fs", "mkdir", f"{VOLUME}/{folder}")
        cli("fs", "cp", str(path), f"{VOLUME}/{folder}/{name}")


def sql(stmt):
    global warehouse
    if not warehouse:
        t = cli("warehouses", "list", "-o", "json").stdout
        warehouse = json.loads(t[t.find("["):])[0]["id"]
    body = json.dumps({"warehouse_id": warehouse, "statement": stmt, "wait_timeout": "50s"})
    t = cli("api", "post", "/api/2.0/sql/statements", "--json", body).stdout
    d = json.loads(t[t.find("{"):])
    if d["status"]["state"] != "SUCCEEDED":
        return f"SQL ERROR: {d['status'].get('error', {}).get('message', '')[:200]}"
    return d.get("result", {}).get("data_array", [])


def one(stmt):
    rows = sql(stmt)
    return rows if isinstance(rows, str) else (rows[0][0] if rows else None)


def count(table, where="TRUE"):
    return one(f"SELECT COUNT(*) FROM {S}{table} WHERE {where}")


def check(name, got, want):
    ok = str(got) == str(want)
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'} {name}: got {got}" + ("" if ok else f", wanted {want}"), flush=True)


def sale(parcel, date, price, addr, zip_code, kind="residential", extra=""):
    return f"Franklin,{parcel},{date},{price},{addr},{zip_code},{kind},r,2026-11-01T08:00:00{extra}"


def report(rows, fetched):
    return f"u1,Franklin,residential,2026-10-23,2026-10-29,2026-11-01,{rows},300000,300000,{rows},{fetched}"


def zillow(rid, name, state, values):
    return f"{rid},1,{name},county,{state},{state},m,39,049,{','.join(str(v) for v in values)}"


def stage1():
    print("Stage 1: first load", flush=True)
    land("auditor_sale", "sale_1.csv", [
        SALE,
        sale("P-1", "2026-10-27", 300000, "1 MAIN ST", "43215"),
        sale("P-2", "2026-10-27", 500000, "2 MAIN ST", "43215"),  # same deed, two parcels
        sale("P-3", "2026-10-27", 500000, "2 MAIN ST", "43215"),
        sale("P-4", "2026-10-27", 10, "3 MAIN ST", "43215"),  # nominal
        sale("P-5", "2026-10-27", 900000, "4 MAIN ST", "43215", kind="commercial"),
    ])
    land("auditor_report", "report_1.csv", [REPORT, report(5, "2026-11-01T08:00:00")])
    land("zillow_county", "zillow_1.csv", [
        f"{ZILLOW},2026-08-31,2026-09-30",
        zillow(1, "Franklin County", "OH", [290000, 291000]),
        zillow(2, "Franklin County", "PA", [100000, 101000]),  # same name, wrong state
    ])
    check("pipeline", run("test"), 0)
    check("bronze sales", count("bronze_auditor_sale"), 5)
    check("silver sales: deed collapsed, nominal and commercial out", count("silver_sale"), 2)
    check("zillow rows, Ohio only", count("silver_zillow_county"), 2)


def stage2():
    print("Stage 2: run again with no new files", flush=True)
    check("pipeline", run("test"), 0)
    check("bronze sales unchanged", count("bronze_auditor_sale"), 5)
    check("still one load time", one(f"SELECT COUNT(DISTINCT loaded_at) FROM {S}bronze_auditor_sale"), 1)


def stage3():
    print("Stage 3: schema drift, new versions, new Zillow release", flush=True)
    land("auditor_sale", "sale_2.csv", [
        SALE + ",buyer_type",
        sale("P-6", "2026-10-28", 400000, "5 MAIN ST", "43215", extra=",LLC"),
    ])
    land("auditor_report", "report_2.csv", [REPORT, report(6, "2026-11-02T08:00:00")])
    land("zillow_county", "zillow_2.csv", [
        f"{ZILLOW},2026-08-31,2026-09-30,2026-10-31",
        zillow(1, "Franklin County", "OH", [290000, 299999, 305000]),  # September revised
        zillow(2, "Franklin County", "PA", [100000, 101000, 102000]),
    ])
    check("pipeline recovers from drift", run("test"), 0)
    columns = [r[0] for r in sql(f"SHOW COLUMNS IN {S}bronze_auditor_sale")]
    check("new column added to bronze", "buyer_type" in columns, True)
    value = one(f"SELECT buyer_type FROM {S}bronze_auditor_sale WHERE parcel_id = 'P-6'")
    check("new row has its value", value, "LLC")
    check("older rows have no value", count("bronze_auditor_sale", "buyer_type IS NOT NULL"), 1)
    # An empty buyer_type column did appear in this table after the restart, so check where the value went.
    rescued = one(f"SELECT _rescued_data FROM {S}bronze_sale_rescue_mode WHERE parcel_id = 'P-6'")
    check("rescue mode captured the value", "LLC" in str(rescued), True)
    check("rescue mode didn't fill a column", count("bronze_sale_rescue_mode", "buyer_type IS NOT NULL"), 0)
    check("silver sales", count("silver_sale"), 3)
    check("bronze keeps both report versions", count("bronze_auditor_report"), 2)
    check("silver keeps the latest report", one(f"SELECT parsed_rows FROM {S}silver_report"), 6)
    check("bronze keeps both Zillow releases", count("bronze_zillow_county"), 4)
    check("silver uses the revised value",
          one(f"SELECT zhvi FROM {S}silver_zillow_county WHERE month = '2026-09-01'"), 299999.0)
    check("silver has the new month", count("silver_zillow_county"), 3)


def stage4():
    print("Stage 4: bad rows", flush=True)
    land("auditor_sale", "sale_3.csv", [
        SALE,
        sale("B-1", "", 350000, "6 MAIN ST", "43215"),  # no date
        sale("B-2", "not-a-date", 350000, "7 MAIN ST", "43215"),  # bad date
        sale("B-3", "2026-10-28", "abc", "8 MAIN ST", "43215"),  # bad price
        sale("B-4", "2026-10-28", 360000, "9 MAIN ST", ""),  # no ZIP: kept and counted
    ])
    check("pipeline survives bad rows", run("test"), 0)
    check("bronze keeps the bad rows", count("bronze_auditor_sale", "parcel_id LIKE 'B-%'"), 4)
    check("silver drops the three bad rows", count("silver_sale", "parcel_id LIKE 'B-%'"), 1)
    kept = one(f"SELECT parcel_id FROM {S}silver_sale WHERE zip IS NULL")
    check("silver keeps the row with no ZIP", kept, "B-4")


if __name__ == "__main__":
    print("Deploying test target", flush=True)
    cli("bundle", "deploy", "-t", "test", cwd=HERE)
    for stage in (stage1, stage2, stage3, stage4):
        stage()
    print(f"\n{sum(results)} of {len(results)} checks passed")
    sys.exit(0 if all(results) else 1)
