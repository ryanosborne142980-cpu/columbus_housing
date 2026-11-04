"""County auditor sales exports (CSV/TSV/Excel) -> auditor_sale.

For counties without a weekly sales report to scrape:
  Delaware: https://auditor.co.delaware.oh.us/propinfo/ -> The Whole County -> Residential ->
            Sold Since a Specific Date. The file arrives by email within ~15 minutes.
  Licking:  no public bulk export found; request a sales file from the auditor's office.
No sample of either export was on hand, so columns are matched by header name. If a load
fails, the error lists the file's columns; add the header to COLUMN_HINTS.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from . import db

log = logging.getLogger(__name__)

COUNTIES = ("Delaware", "Licking")

# First hint that matches a (snake_cased) header wins, so order matters within each list.
COLUMN_HINTS = {
    "parcel_id": ["parcel", "parid", "pin"],
    "sale_date": ["sale_date", "saledt", "sale_dt", "transfer_date", "conveyance_date", "date"],
    "sale_price": ["sale_price", "saleprice", "sale_amount", "sale_amt", "price", "consideration"],
    "site_address": ["site_address", "property_address", "location", "situs", "address"],
    "zip": ["zip"],
    "land_use": ["land_use", "luc", "use_code", "class"],
}
# Owner/mailing columns hold the buyer's address, not the property's.
_NOT_PROPERTY = re.compile(r"owner|mail|buyer|seller|grantor|grantee")
_ZIP_RE = re.compile(r"\b(4[3-5]\d{3})\b")  # central Ohio ZIPs


def _snake(c: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_")


def _read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in (".xls", ".xlsx"):
        return pd.read_excel(path, dtype=str)
    return pd.read_csv(path, sep=None, engine="python", dtype=str)


def _map_columns(cols: list[str]) -> dict[str, str]:
    out = {}
    cols = [c for c in cols if not _NOT_PROPERTY.search(c)]
    for field, hints in COLUMN_HINTS.items():
        for hint in hints:
            match = next((c for c in cols if hint in c and c not in out.values()), None)
            if match:
                out[field] = match
                break
    return out


def _is_residential(v: str) -> bool:
    """Ohio land use codes 500-599 are residential; class columns use 'R' or 'Residential'."""
    v = str(v).strip().upper()
    if v[:3].isdigit():
        return 500 <= int(v[:3]) <= 599
    return v.startswith("R")


def parse(path: Path) -> list[dict]:
    df = _read(path)
    df.columns = [_snake(c) for c in df.columns]
    cm = _map_columns(list(df.columns))
    missing = {"parcel_id", "sale_date", "sale_price"} - cm.keys()
    if missing:
        raise ValueError(f"{path.name}: no column for {sorted(missing)}. Columns: {list(df.columns)}")
    log.info("%s: column map %s", path.name, cm)

    if "land_use" in cm:
        before = len(df)
        df = df[df[cm["land_use"]].map(_is_residential)]
        log.info("%s: kept %s of %s rows as residential", path.name, len(df), before)

    dates = pd.to_datetime(df[cm["sale_date"]], errors="coerce")
    prices = pd.to_numeric(df[cm["sale_price"]].str.replace(r"[^\d.]", "", regex=True),
                           errors="coerce")
    addr = df[cm["site_address"]] if "site_address" in cm else pd.Series(None, index=df.index)
    if "zip" in cm:
        zips = df[cm["zip"]].str.extract(_ZIP_RE, expand=False)
    else:
        zips = addr.astype(str).str.extract(_ZIP_RE, expand=False)

    sales, skipped = [], 0
    for parcel, d, p, a, z in zip(df[cm["parcel_id"]], dates, prices, addr, zips, strict=True):
        if pd.isna(d) or pd.isna(p) or not str(parcel).strip():
            skipped += 1
            continue
        sales.append({"parcel_id": str(parcel).strip(), "sale_date": d.date().isoformat(),
                      "sale_price": int(p), "site_address": None if pd.isna(a) else str(a).strip(),
                      "zip": None if pd.isna(z) else z})
    if skipped:
        log.warning("%s: skipped %s rows missing parcel, date or price", path.name, skipped)
    return sales


def load(con, county: str, file: str) -> int:
    path = Path(file)
    sales = parse(path)
    url = f"file:{county.lower()}:{path.name}"
    dates = [s["sale_date"] for s in sales]
    db.upsert_report(con, {"report_url": url, "county": county, "report_type": "residential",
                           "period_start": min(dates, default=None),
                           "period_end": max(dates, default=None), "parsed_rows": len(sales)})
    n = db.insert_new_sales(con, [{**s, "county": county, "report_type": "residential",
                                   "report_url": url} for s in sales])
    con.commit()
    log.info("%s %s: %s rows parsed, %s new", county, path.name, len(sales), n)
    return n
