"""Redfin Data Center weekly housing-market tracker -> redfin_columbus_weekly.

Keeps the Columbus metro row plus the Franklin, Delaware and Licking county rows.

Redfin rebuilt its Data Center in May 2026; download links on
https://www.redfin.com/news/data-center/downloads/ are JS-rendered. Two ways in:
  1. --file: CSV/TSV(.gz) you downloaded from the Download Hub (always works).
  2. --url:  direct file URL. DEFAULT_URL is Redfin's long-standing public S3 weekly
     file; verify it still updates before relying on it.
Weekly values are rolling 4-week windows and are revised, so each load fully replaces.
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path

import pandas as pd

from . import db, http

log = logging.getLogger(__name__)

# Redfin's public weekly file (all US regions, all history) used when no --file or --url is given.
DEFAULT_URL = ("https://redfin-public-data.s3.us-west-2.amazonaws.com/"
               "redfin_covid19/weekly_housing_market_data_most_recent.tsv000")
# Region names to keep: the Columbus metro plus the three county rows, Ohio only.
REGION_MATCH = re.compile(r"columbus,?\s*oh|\b(?:franklin|delaware|licking) county,\s*oh\b",
                          re.I)
# Destination table; dropped and rebuilt on every load.
TABLE = "redfin_columbus_weekly"


def _snake(c: str) -> str:
    # "Median Sale Price" -> "median_sale_price", so column names are stable across file versions.
    return re.sub(r"[^a-z0-9]+", "_", c.strip().lower()).strip("_")


def _read(buf: bytes | Path, name: str) -> pd.DataFrame:
    # Detect gzip by file extension or by the gzip magic bytes (S3 files can be gzipped without .gz).
    comp = "gzip" if name.endswith(".gz") or (isinstance(buf, bytes) and buf[:2] == b"\x1f\x8b") else None
    # Downloaded content arrives as bytes; wrap it so pandas can read it like a file.
    src = io.BytesIO(buf) if isinstance(buf, bytes) else buf
    # Sniff delimiter: Redfin S3 files are TSV, Download Hub files are CSV.
    return pd.read_csv(src, sep=None, engine="python", compression=comp, na_values=["NA", ""])


def load(con, *, file: str | None = None, url: str | None = None) -> int:
    """Load Redfin's weekly file, keep Columbus-area rows, replace the table. Returns rows kept."""
    # Read from a local file if given; otherwise download (whole file into memory).
    if file:
        df, source = _read(Path(file), file), file
    else:
        url = url or DEFAULT_URL
        r = http.get(url, timeout=600, check_robots=False)  # S3 object, no robots.txt
        r.raise_for_status()
        df, source = _read(r.content, url), url

    # Normalize headers, then find the region-name column(s) (skip region_type / region_id).
    df.columns = [_snake(c) for c in df.columns]
    region_cols = [c for c in df.columns if "region" in c and "type" not in c and "id" not in c]
    if not region_cols:
        raise ValueError(f"No region column found. Columns: {list(df.columns)[:20]}")
    # Keep rows where any region column matches Columbus metro or one of the three counties.
    mask = pd.Series(False, index=df.index)
    for c in region_cols:
        mask |= df[c].astype(str).str.contains(REGION_MATCH)
    df = df[mask].copy()
    # Zero matches usually means Redfin renamed its regions; fail loudly rather than load nothing.
    if df.empty:
        raise ValueError("No Columbus-area rows. Check the region naming in this file.")

    # Convert period/date columns to real dates so they land as DATE in SQL Server (bad values -> NULL).
    for c in [c for c in df.columns if "period" in c or c.endswith("date")]:
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.date

    # Replace the table with this load, log the load, and commit both together.
    db.replace_table(con, TABLE, df)
    con.execute("INSERT INTO redfin_load_log (source, rows_loaded, columns) VALUES (?,?,?)",
                (source, len(df), ",".join(df.columns)))
    con.commit()
    log.info("redfin: %s Columbus-area rows, %s columns", len(df), len(df.columns))
    return len(df)
