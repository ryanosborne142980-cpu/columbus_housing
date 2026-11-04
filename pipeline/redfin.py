"""Redfin Data Center weekly housing-market tracker -> redfin_columbus_weekly.

Keeps the Columbus metro row plus the Franklin, Delaware and Licking county rows.

Redfin rebuilt its Data Center in May 2026. The old public S3 weekly file stopped updating
in March 2025 and the old market-tracker paths now return 403, and the new download links on
https://www.redfin.com/news/data-center/ are JS-rendered. So:
  1. --file: CSV/TSV(.gz) you downloaded from the Data Center (the normal way).
  2. --url:  a direct file URL, if you find one that is current.
Files can be large (all US regions), so they are read in chunks and filtered as they go.
Weekly values are rolling 4-week windows and are revised, so each load fully replaces.
Credit Redfin wherever this data is shown (ATTRIBUTION).
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path

import pandas as pd

from . import db, http

log = logging.getLogger(__name__)

ATTRIBUTION = "Redfin Data Center, Redfin (a national real estate brokerage) - https://www.redfin.com/news/data-center/"
CHUNK_ROWS = 200_000
# Region names to keep: the Columbus metro plus the three county rows, Ohio only.
REGION_MATCH = re.compile(r"columbus,?\s*oh|\b(?:franklin|delaware|licking) county,\s*oh\b",
                          re.I)
# Destination table; dropped and rebuilt on every load.
TABLE = "redfin_columbus_weekly"


def _snake(c: str) -> str:
    # "Median Sale Price" -> "median_sale_price", so column names are stable across file versions.
    return re.sub(r"[^a-z0-9]+", "_", c.strip().lower()).strip("_")


def _read(buf: bytes | Path, name: str) -> pd.DataFrame:
    """Read a Redfin file in chunks, keeping only Columbus-area rows (all values as text)."""
    # Gzip by extension or magic bytes (S3 files can be gzipped without .gz).
    head = buf[:2] if isinstance(buf, bytes) else Path(buf).open("rb").read(2)
    comp = "gzip" if name.endswith(".gz") or head == b"\x1f\x8b" else None
    src = (lambda: io.BytesIO(buf)) if isinstance(buf, bytes) else (lambda: buf)
    # Sniff the delimiter from the first rows only (Data Center: CSV or TSV).
    sep = pd.read_csv(src(), sep=None, engine="python", compression=comp, nrows=5).columns
    sep = "\t" if len(sep) == 1 and "\t" in sep[0] else None
    if sep is None:
        sample = pd.read_csv(src(), sep="\t", compression=comp, nrows=5)
        sep = "\t" if len(sample.columns) > 1 else ","
    kept, region_cols = [], None
    for chunk in pd.read_csv(src(), sep=sep, compression=comp, dtype=str, na_values=["NA", ""],
                             chunksize=CHUNK_ROWS):
        chunk.columns = [_snake(c) for c in chunk.columns]
        if region_cols is None:
            region_cols = [c for c in chunk.columns
                           if "region" in c and "type" not in c and "id" not in c]
            if not region_cols:
                raise ValueError(f"No region column found. Columns: {list(chunk.columns)[:20]}")
        mask = pd.Series(False, index=chunk.index)
        for c in region_cols:
            mask |= chunk[c].fillna("").str.contains(REGION_MATCH)
        if mask.any():
            kept.append(chunk[mask])
    if not kept:
        raise ValueError("No Columbus-area rows. Check the region naming in this file.")
    df = pd.concat(kept, ignore_index=True)
    # Text -> numbers where every non-blank value is numeric.
    for c in df.columns:
        num = pd.to_numeric(df[c], errors="coerce")
        if num.notna().sum() == df[c].notna().sum() and df[c].notna().any():
            df[c] = num
    return df


def load(con, *, file: str | None = None, url: str | None = None) -> int:
    """Load Redfin's weekly file, keep Columbus-area rows, replace the table. Returns rows kept."""
    if file:
        df, source = _read(Path(file), file), file
    elif url:
        r = http.get(url, timeout=600)
        r.raise_for_status()
        df, source = _read(r.content, url), url
    else:
        raise ValueError("Redfin needs --file (download from https://www.redfin.com/news/data-center/) "
                         "or --url. The old default S3 file stopped updating in March 2025.")

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
