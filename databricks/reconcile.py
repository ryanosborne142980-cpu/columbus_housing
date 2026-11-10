"""Check that Databricks matches SQL Server, after new rows have been landed and the pipeline has run.

Run from the repo root:  python databricks/reconcile.py

Compares silver with SQL Server on row counts, totals and date ranges, and exits 1 on any difference.
It uses silver because bronze keeps every version of a row, so its totals grow when a report is re-parsed.
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import db  # noqa: E402

SCHEMA = "workspace.columbus_housing"
PROFILE = "columbus"
POLL_SECONDS = 5
MAX_POLLS = 60
# name -> (SQL Server query, Databricks query), selecting the same measures in the same order.
_SALES = "COUNT(*), SUM(CAST(sale_price AS BIGINT)), MIN(sale_date), MAX(sale_date)"
_REPORTS = "COUNT(*), SUM(CAST(parsed_rows AS BIGINT)), MIN(period_start), MAX(period_end)"
CHECKS = {
    "sales": (f"SELECT {_SALES} FROM v_sale_clean", f"SELECT {_SALES} FROM {SCHEMA}.silver_sale"),
    "reports": (f"SELECT {_REPORTS} FROM auditor_report", f"SELECT {_REPORTS} FROM {SCHEMA}.silver_report"),
}


def differences(name: str, ours, theirs) -> list[str]:
    """Compare two rows as text, since the statements API returns every value as a string."""
    ours, theirs = [str(v) for v in ours], [str(v) for v in theirs]
    return [] if ours == theirs else [f"{name}: SQL Server {ours}, Databricks {theirs}"]


def _api(cli: str, method: str, path: str, *args) -> dict:
    r = subprocess.run([cli, "api", method, path, "-p", PROFILE, *args], capture_output=True, text=True,
                       encoding="utf-8", check=True)
    return json.loads(r.stdout)


def _query(cli: str, warehouse: str, sql: str) -> list:
    body = json.dumps({"warehouse_id": warehouse, "statement": sql, "wait_timeout": "50s"})
    result = _api(cli, "post", "/api/2.0/sql/statements", "--json", body)
    for _ in range(MAX_POLLS):
        state = result["status"]["state"]
        if state == "SUCCEEDED":
            return result["result"]["data_array"][0]
        if state not in ("PENDING", "RUNNING"):
            raise RuntimeError(f"Databricks query {state}: {result['status'].get('error')}")
        time.sleep(POLL_SECONDS)
        result = _api(cli, "get", f"/api/2.0/sql/statements/{result['statement_id']}")
    raise TimeoutError("Databricks query didn't finish")


def main() -> int:
    cli = shutil.which("databricks")
    if not cli:
        print("databricks CLI not on PATH", file=sys.stderr)
        return 1
    warehouses = json.loads(subprocess.run(
        [cli, "warehouses", "list", "-p", PROFILE, "-o", "json"], capture_output=True, text=True,
        encoding="utf-8", check=True).stdout)
    warehouse = warehouses[0]["id"]
    con = db.connect()
    problems = []
    for name, (ours, theirs) in CHECKS.items():
        row = tuple(con.execute(ours).fetchone())
        other = _query(cli, warehouse, theirs)
        problems += differences(name, row, other)
        print(f"{name}: {[str(v) for v in row]}")
    for problem in problems:
        print(problem, file=sys.stderr)
    print("reconcile:", "DIFFERENT" if problems else "match")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
