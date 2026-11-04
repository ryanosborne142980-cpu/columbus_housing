"""Export new SQL Server rows to CSV files for landing elsewhere.

Each table has a column that says when a row last changed. A run exports only rows newer than the
last run's high point, so landing the files keeps bronze append-only. A report re-parsed later gets
a new fetched_at and is exported again; silver picks the latest version.
"""
from __future__ import annotations

from pathlib import Path

from . import db

# Table -> (change-tracking column, what that column is called in the file).
# auditor_sale.loaded_at is renamed so it can't collide with the load time bronze adds.
TABLES = {
    "auditor_sale": ("loaded_at", "source_loaded_at"),
    "auditor_report": ("fetched_at", "fetched_at"),
}


def export_new(con, table: str, since: str | None, out_dir: Path) -> tuple[Path | None, str | None, int]:
    """Write rows newer than `since`. Returns (file, new high point, rows); file is None if no new rows.

    The file is named for its high point, so retrying the same export produces the same file name.
    """
    column, label = TABLES[table]  # KeyError for anything else; names below come only from TABLES
    where = f"WHERE [{column}] > ?" if since else ""
    params = [since] if since else []
    high = con.execute(f"SELECT MAX([{column}]) FROM dbo.[{table}] {where}", *params).fetchone()[0]
    if high is None:
        return None, since, 0
    stamp = high.strftime("%Y-%m-%dT%H:%M:%S")

    df = db.query_df(con, f"SELECT * FROM dbo.[{table}] WHERE [{column}] <= ? "
                          + (f"AND [{column}] > ?" if since else ""), stamp, *params)
    df = df.rename(columns={column: label})
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{table}_{high:%Y%m%d_%H%M%S}.csv"
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    return path, stamp, len(df)
