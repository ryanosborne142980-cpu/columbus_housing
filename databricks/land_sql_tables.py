"""Land new SQL Server rows in the Databricks volume as CSV files.

Run from the repo root:  python databricks/land_sql_tables.py

Databricks can't reach this SQL Server, which only listens on localhost, so rows travel as files.
The high point moves forward only after a file uploads, so a failed run is simply run again.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import db, export  # noqa: E402

LOCAL = Path("data/landing")
STATE = LOCAL / "sql_export_state.json"
VOLUME = "dbfs:/Volumes/workspace/columbus_housing/raw"
PROFILE = "columbus"


def main() -> int:
    cli = shutil.which("databricks")
    if not cli:
        print("databricks CLI not on PATH", file=sys.stderr)
        return 1
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    con = db.connect()
    for table in export.TABLES:
        path, high, rows = export.export_new(con, table, state.get(table), LOCAL / table)
        if path is None:
            print(f"{table}: nothing new")
            continue
        target = f"{VOLUME}/{table}"
        subprocess.run([cli, "fs", "mkdir", target, "-p", PROFILE], check=True)
        subprocess.run([cli, "fs", "cp", str(path), f"{target}/{path.name}", "-p", PROFILE], check=True)
        state[table] = high
        STATE.write_text(json.dumps(state, indent=2))
        print(f"{table}: landed {rows} rows in {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
