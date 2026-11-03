"""SQL Server storage. Schema + views live in sql/.

This is a library module used by run.py; it loads no data itself. To run the pipeline:
    python run.py report | auditor | county-file | redfin | all     (see run.py)
Running this file directly (python pipeline/db.py) only checks the connection: it creates the
database/tables/views if missing and prints each table's row count.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

import pandas as pd
import pyodbc

# Project root (two levels up from this file: pipeline/db.py -> repo root).
ROOT = Path(__file__).resolve().parent.parent
# Connection defaults; override with env vars or run.py --db / --server.
DEFAULT_SERVER = os.environ.get("COLUMBUS_HOUSING_SERVER", r".\ROSBO_SQL")
DEFAULT_DB = os.environ.get("COLUMBUS_HOUSING_DB", "columbus_housing")
DRIVER = "ODBC Driver 18 for SQL Server"
# sql/*.sql files are split into batches on lines containing only GO (CREATE VIEW must start a batch).
_GO = re.compile(r"^\s*GO\s*$", re.I | re.M)
# Columns an auditor_sale insert carries, in staging-table order.
SALE_COLS = ("county", "parcel_id", "sale_date", "sale_price", "site_address", "zip",
             "report_type", "report_url")


def _conn_str(server: str, database: str) -> str:
    # Windows auth (no stored password). Local instance uses a self-signed cert, hence TrustServerCertificate.
    return (f"DRIVER={{{DRIVER}}};SERVER={server};DATABASE={database};"
            "Trusted_Connection=yes;TrustServerCertificate=yes")


def connect(database: str = DEFAULT_DB, server: str = DEFAULT_SERVER) -> pyodbc.Connection:
    """Open the database, creating it and its tables and views if needed."""
    # CREATE DATABASE can't run inside a transaction, so do it from master with autocommit.
    # Explicit close: pyodbc's `with` commits on exit but leaves the connection open.
    m = pyodbc.connect(_conn_str(server, "master"), autocommit=True)
    try:
        m.execute(f"IF DB_ID(?) IS NULL CREATE DATABASE [{database}]", database)
    finally:
        m.close()
    con = pyodbc.connect(_conn_str(server, database))
    # Apply schema + views on every connect so the DB always matches sql/.
    init(con)
    return con


def init(con: pyodbc.Connection) -> None:
    """Run sql/schema.sql then sql/views.sql. Safe to repeat on every connect."""
    # Order matters: views reference the tables. schema.sql creates only missing tables
    # (keeps data); views.sql uses CREATE OR ALTER (picks up edits to views.sql).
    cur = con.cursor()
    for name in ("schema.sql", "views.sql"):
        for batch in _GO.split((ROOT / "sql" / name).read_text()):
            if batch.strip():
                cur.execute(batch)
    con.commit()


def query_df(con: pyodbc.Connection, sql: str, *params) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame (pandas' read_sql only supports SQLAlchemy for SQL Server)."""
    cur = con.execute(sql, *params)
    cols = [d[0] for d in cur.description]
    return pd.DataFrame.from_records([tuple(r) for r in cur.fetchall()], columns=cols)


def insert_new_sales(con: pyodbc.Connection, rows: list[dict]) -> int:
    """Insert sales not already in auditor_sale; return how many were new. Caller commits."""
    if not rows:
        return 0
    cur = con.cursor()
    # Bulk-load into a temp table, then copy across only keys not already present.
    # Drop first: a failed earlier call on this connection can leave #stage behind.
    cur.execute("DROP TABLE IF EXISTS #stage")
    cur.execute("""CREATE TABLE #stage (county NVARCHAR(20), parcel_id NVARCHAR(50), sale_date DATE,
                   sale_price INT, site_address NVARCHAR(200), zip NVARCHAR(10),
                   report_type NVARCHAR(20), report_url NVARCHAR(450))""")
    cur.fast_executemany = True
    cur.executemany(f"INSERT INTO #stage VALUES ({','.join('?' * len(SALE_COLS))})",
                    [tuple(dt.date.fromisoformat(r[c]) if c == "sale_date" else r[c] for c in SALE_COLS)
                     for r in rows])
    # ROW_NUMBER drops duplicate keys within the same file (first one wins).
    cur.execute(f"""
        INSERT INTO auditor_sale ({','.join(SALE_COLS)})
        SELECT {','.join(SALE_COLS)} FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY county, parcel_id, sale_date, sale_price
                                         ORDER BY (SELECT NULL)) AS rn
            FROM #stage) s
        WHERE rn = 1 AND NOT EXISTS (
            SELECT 1 FROM auditor_sale a
            WHERE a.county = s.county AND a.parcel_id = s.parcel_id
              AND a.sale_date = s.sale_date AND a.sale_price = s.sale_price)""")
    n = cur.rowcount
    cur.execute("DROP TABLE #stage")
    return n


def upsert_report(con: pyodbc.Connection, row: dict) -> None:
    """Insert or update one auditor_report row keyed on report_url. Caller commits."""
    sets = ", ".join(f"{k} = ?" for k in row if k != "report_url")
    cur = con.execute(f"UPDATE auditor_report SET {sets}, fetched_at = SYSUTCDATETIME() WHERE report_url = ?",
                      *[v for k, v in row.items() if k != "report_url"], row["report_url"])
    if cur.rowcount == 0:
        con.execute(f"INSERT INTO auditor_report ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                    *row.values())


def _sql_type(s: pd.Series) -> str:
    # Map a pandas column to a SQL Server type for replace_table.
    if pd.api.types.is_bool_dtype(s):
        return "BIT"
    if pd.api.types.is_integer_dtype(s):
        return "BIGINT"
    if pd.api.types.is_float_dtype(s):
        return "FLOAT"
    vals = s.dropna()
    if len(vals) and all(isinstance(v, dt.date) for v in vals):
        return "DATE"
    return "NVARCHAR(4000)"


def replace_table(con: pyodbc.Connection, table: str, df: pd.DataFrame) -> None:
    """Drop and recreate `table` from a DataFrame (column types inferred). Caller commits."""
    cur = con.cursor()
    cur.execute(f"DROP TABLE IF EXISTS [{table}]")
    cur.execute(f"CREATE TABLE [{table}] ("
                + ", ".join(f"[{c}] {_sql_type(df[c])}" for c in df.columns) + ")")
    if df.empty:
        return
    # NaN/NaT -> None so they land as NULL.
    rows = df.astype(object).where(df.notna(), None).values.tolist()
    cur.fast_executemany = True
    cur.executemany(f"INSERT INTO [{table}] VALUES ({','.join('?' * len(df.columns))})", rows)


if __name__ == "__main__":
    # Connection check only; the pipeline itself runs from run.py.
    con = connect()
    print(f"Connected: {DEFAULT_SERVER} / {DEFAULT_DB}")
    for (t,) in con.execute("SELECT name FROM sys.tables ORDER BY name").fetchall():
        print(f"  {t}: {con.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]} rows")
    print("To load or report data, run: python run.py --help")
