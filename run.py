"""CLI.

  python run.py auditor --since 2025-10-01            # backfill/incremental Franklin weekly sales
  python run.py county-file --county Delaware --file x.csv   # Delaware/Licking sales export
  python run.py redfin  --file path [| --url url]     # Redfin weekly tracker (manual download)
  python run.py auditor --url <report page>            # load one report discovery can't find
  python run.py reparse                             # re-parse saved raw pages after a parser fix
  python run.py zillow  [--kind county|zip] [--file path | --url url]   # monthly; skips unchanged files
  python run.py backup                                # verified backup, copied to OneDrive
  python run.py report  [--export out/]               # trend summary (+ CSV export)
  python run.py all     --since 2025-10-01            # auditor + redfin + report
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from pipeline import auditor, backup, county_file, db, quality, redfin, zillow


def report(con, export: str | None) -> None:
    pd.set_option("display.width", 140)

    def q(sql):
        return db.query_df(con, sql)

    roll = q("""SELECT * FROM (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY county ORDER BY week_start DESC) AS rn
                    FROM v_county_rolling4) t
                WHERE rn <= 8 ORDER BY county, week_start DESC""").drop(columns="rn")
    print("\n== Residential by county: rolling 4-week (latest 8 per county) ==")
    print(roll.to_string(index=False) if not roll.empty else "(no auditor data)")

    zips = q("""SELECT zip, month, sales, median_price, median_yoy_pct FROM v_zip_month
                WHERE month = (SELECT MAX(month) FROM v_zip_month
                               WHERE month < CONVERT(char(7), GETDATE(), 126))
                  AND low_sample = 0 ORDER BY median_yoy_pct DESC""")
    print("\n== ZIPs, last full month (>=10 sales) ==")
    print(zips.to_string(index=False) if not zips.empty else "(need >=1 month + prior year for YoY)")

    bad = q("SELECT * FROM v_report_validation WHERE diff <> 0")
    if not bad.empty:
        print("\n!! Parser drift: parsed rows != county snapshot count")
        print(bad.to_string(index=False))

    try:
        rf = q(f"SELECT * FROM {redfin.TABLE}")
        cols = [c for c in rf.columns if any(k in c for k in
                ("region_name", "period_end", "median_sale_price", "inventory", "pending", "new_listings",
                 "days_on_market", "price_drop", "sale_to_list"))]
        cols = cols or list(rf.columns)[:10]
        sort = next((c for c in cols if "period_end" in c), cols[0])
        region = next((c for c in cols if "region_name" in c), None)
        latest = rf.sort_values(sort, ascending=False)
        latest = latest.groupby(region).head(4) if region else latest.head(8)
        print("\n== Redfin Columbus metro + counties, latest 4 per region ==")
        print(latest[cols].to_string(index=False))
        print(f"Source: {redfin.ATTRIBUTION}")
    except Exception:
        print("\n(no Redfin data loaded)")

    zv = q("""SELECT region_name, month, zhvi, zhvi_yoy_pct FROM v_zillow_yoy
              WHERE region_type = 'county' AND month = (SELECT MAX(month) FROM zillow_zhvi)
              ORDER BY region_name""")
    if not zv.empty:
        print("\n== Zillow home value index by county, latest month ==")
        print(zv.to_string(index=False))
        print(f"Source: {zillow.ATTRIBUTION}")

    if export:
        out = Path(export)
        out.mkdir(parents=True, exist_ok=True)
        for v in ("v_county_week", "v_county_rolling4", "v_zip_month", "v_sale_clean"):
            q(f"SELECT * FROM {v}").to_csv(out / f"{v}.csv", index=False)
        # Zillow requires attribution wherever its data goes, so it travels with the export.
        q("SELECT * FROM v_zillow_yoy").to_csv(out / "v_zillow_yoy.csv", index=False)
        (out / "ATTRIBUTION.txt").write_text(f"v_zillow_yoy.csv: {zillow.ATTRIBUTION}\n")
        print(f"\nExported views to {out.resolve()}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["auditor", "reparse", "county-file", "redfin", "zillow", "report",
                                   "backup", "check", "all"])
    p.add_argument("--county", choices=county_file.COUNTIES, help="county for county-file")
    p.add_argument("--db", default=db.DEFAULT_DB, help="SQL Server database name")
    p.add_argument("--server", default=db.DEFAULT_SERVER, help="SQL Server instance")
    p.add_argument("--since", type=date.fromisoformat, default=date.today() - timedelta(days=56))
    p.add_argument("--commercial", action="store_true", help="also load commercial sales")
    p.add_argument("--refetch", action="store_true", help="re-pull reports already loaded")
    p.add_argument("--file", help="local file: Redfin CSV/TSV(.gz), county export, or Zillow CSV")
    p.add_argument("--url", help="one Franklin report page, or a Redfin or Zillow file URL")
    p.add_argument("--kind", choices=list(zillow.URLS), help="Zillow file: county or zip (default both)")
    p.add_argument("--export", help="dir to write view CSVs")
    p.add_argument("-v", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format="%(levelname)s %(message)s")

    con = db.connect(a.db, a.server)
    problems = []
    if a.cmd in ("auditor", "all"):
        types = ("residential", "commercial") if a.commercial else ("residential",)
        if a.cmd == "auditor" and a.url:
            print("auditor new rows:", auditor.load_url(con, a.url))
        else:
            stats = auditor.run(con, a.since, types, a.refetch)
            print("auditor:", stats)
            problems = auditor.run_problems(con, stats)
    if a.cmd == "backup":
        print("backup:", backup.run(con))
    if a.cmd == "check":
        findings = quality.check(con)
        quality.print_report(findings)
        problems = [f"{f.rule.name}: {len(f.rows)}" for f in quality.failures(findings)]
    if a.cmd == "reparse":
        print("reparse:", auditor.reparse(con))
    if a.cmd == "county-file":
        if not (a.county and a.file):
            p.error("county-file needs --county and --file")
        print("county-file new rows:", county_file.load(con, a.county, a.file))
    if a.cmd == "all" and not (a.file or a.url):
        print("redfin: skipped (no --file/--url; download from the Redfin Data Center)")
    elif a.cmd in ("redfin", "all"):
        try:
            print("redfin rows:", redfin.load(con, file=a.file, url=a.url))
        except Exception as e:  # don't let one source kill the run
            logging.error("redfin load failed: %s", e)
            if a.cmd == "redfin":
                return 1
    if a.cmd == "zillow":
        kinds = [a.kind] if a.kind else list(zillow.URLS)
        if (a.file or a.url) and len(kinds) > 1:
            p.error("zillow --file/--url needs --kind county or --kind zip")
        for k in kinds:
            n = zillow.load(con, k, file=a.file, url=a.url)
            print(f"zillow {k}:", "unchanged, skipped" if n is None else f"{n} rows")
    if a.cmd in ("report", "all"):
        report(con, a.export)
    for problem in problems:
        logging.error("run problem: %s", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
