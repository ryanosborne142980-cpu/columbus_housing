"""Zillow Home Value Index (ZHVI) -> zillow_zhvi.

Monthly, smoothed, seasonally adjusted typical home value (all homes, middle price tier) for
the Franklin, Delaware and Licking county rows and every ZIP in those counties, back to 2000.

Rules this loader follows:
  * Terms: Zillow research data is free for public use with clear attribution to Zillow
    (https://zillowgroup.com/developers/api/public-data/real-estate-metrics). Anything shown
    or exported from this table must carry ATTRIBUTION; run.py report does this.
  * Zillow's Terms of Use bar automated scraping, so this only downloads the published CSV
    files below (no page crawling), via pipeline.http (robots.txt + throttle), and skips the
    download when the file's Last-Modified matches the last load. Zillow updates on the 16th
    of each month, so run it monthly, not in the weekly job. --file (a CSV you downloaded from
    https://www.zillow.com/research/data/) needs no network at all.
  * Zillow occasionally moves its CSV paths. If a download 404s, get the new link from the
    data page and pass it with --url, or download it and use --file.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd

from . import http

log = logging.getLogger(__name__)

ATTRIBUTION = "Zillow Home Value Index (ZHVI), Zillow Group - https://www.zillow.com/research/data/"
_BASE = "https://files.zillowstatic.com/research/public_csvs/zhvi/"
URLS = {
    "county": _BASE + "County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "zip": _BASE + "Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
}
COUNTIES = ("Franklin County", "Delaware County", "Licking County")


def parse(buf: bytes | Path, kind: str) -> pd.DataFrame:
    """Wide Zillow CSV -> long rows (region_type, region_name, county, month, zhvi), OH only."""
    src = io.BytesIO(buf) if isinstance(buf, bytes) else buf
    df = pd.read_csv(src, dtype={"RegionName": str})
    county_col = "RegionName" if kind == "county" else "CountyName"
    need = {"RegionName", "State", county_col}
    if not need <= set(df.columns):
        raise ValueError(f"{kind} file missing {sorted(need - set(df.columns))}. "
                         f"Columns: {list(df.columns)[:12]}")
    df = df[(df["State"] == "OH") & df[county_col].isin(COUNTIES)].copy()
    if df.empty:
        raise ValueError(f"No Franklin/Delaware/Licking rows in the {kind} file.")
    months = [c for c in df.columns if c[:2] in ("19", "20") and c[4:5] == "-"]
    df = df.assign(_county=df[county_col].str.replace(" County", "", regex=False))
    long = df.melt(id_vars=["RegionName", "_county"], value_vars=months,
                   var_name="month", value_name="zhvi").dropna(subset=["zhvi"])
    region = long["RegionName"].str.zfill(5) if kind == "zip" else long["RegionName"]
    return pd.DataFrame({
        "region_type": kind,
        "region_name": region,
        "county": long["_county"],
        # Zillow labels months by their last day; store the first day so it joins on month.
        "month": pd.to_datetime(long["month"]).dt.to_period("M").dt.start_time.dt.date,
        "zhvi": long["zhvi"].astype(float),
    })


def _last_modified(con, kind: str) -> str | None:
    row = con.execute("SELECT TOP 1 last_modified FROM zillow_load_log WHERE region_type = ? "
                      "AND last_modified IS NOT NULL ORDER BY loaded_at DESC", kind).fetchone()
    return row[0] if row else None


def load(con, kind: str, *, file: str | None = None, url: str | None = None) -> int | None:
    """Load one Zillow file (kind 'county' or 'zip'). Returns rows loaded, or None if the
    remote file is unchanged since the last load."""
    if kind not in URLS:
        raise ValueError(f"kind must be one of {list(URLS)}")
    last_mod = None
    if file:
        buf, source = Path(file), file
    else:
        source = url or URLS[kind]
        head = http.head(source)
        head.raise_for_status()
        last_mod = head.headers.get("Last-Modified")
        if last_mod and last_mod == _last_modified(con, kind):
            log.info("zillow %s: unchanged since last load (%s); skipped", kind, last_mod)
            return None
        r = http.get(source, timeout=600)
        r.raise_for_status()
        buf = r.content

    df = parse(buf, kind)
    # Zillow revises history every month, so each load replaces this kind's rows wholesale.
    cur = con.cursor()
    cur.execute("DELETE FROM zillow_zhvi WHERE region_type = ?", kind)
    cur.fast_executemany = True
    cur.executemany("INSERT INTO zillow_zhvi (region_type, region_name, county, month, zhvi) "
                    "VALUES (?,?,?,?,?)", df.values.tolist())
    cur.execute("INSERT INTO zillow_load_log (region_type, source, last_modified, rows_loaded, "
                "attribution) VALUES (?,?,?,?,?)", kind, source, last_mod, len(df), ATTRIBUTION)
    con.commit()
    log.info("zillow %s: %s rows, %s regions, %s to %s", kind, len(df), df["region_name"].nunique(),
             df["month"].min(), df["month"].max())
    return len(df)
