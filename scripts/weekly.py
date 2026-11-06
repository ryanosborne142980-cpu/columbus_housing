"""The weekly job: load Franklin, check the data, back up, then land new rows in Databricks, run
bronze and silver, and check Databricks matches.

Run from anywhere:  python scripts/weekly.py

Every step runs even if an earlier one fails, so a county site outage doesn't also skip the
backup. The exception is a failed data check: Databricks steps are skipped so bad rows stay out
of it, because bronze is append-only. Output goes to data/logs/, with the outcome in last_run.txt.
Exits non-zero if any step failed, which shows up as the task's last result in Task Scheduler.

Zillow isn't here on purpose: it's a monthly, by-hand step (see decision 0006). Nothing sends an
alert yet, so check last_run.txt or Task Scheduler.
"""
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "data" / "logs"
PY = sys.executable
STEPS = [
    ("load Franklin", [PY, "run.py", "all", "--commercial"], ROOT),
    ("check data", [PY, "run.py", "check"], ROOT),
    ("back up", [PY, "run.py", "backup"], ROOT),
    ("land new rows", [PY, "databricks/land_sql_tables.py"], ROOT),
    ("run pipeline", [PY, "databricks/run_pipeline.py"], ROOT),
    ("reconcile", [PY, "databricks/reconcile.py"], ROOT),
]
GATE = "check data"
NEEDS_CLEAN_DATA = {"land new rows", "run pipeline", "reconcile"}


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    failed, skipped = [], []
    with (LOGS / f"weekly_{started:%Y%m%d_%H%M%S}.log").open("w", encoding="utf-8") as log:
        for name, cmd, cwd in STEPS:
            if GATE in failed and name in NEEDS_CLEAN_DATA:
                log.write(f"\n=== {name}: skipped, the data check failed\n")
                skipped.append(name)
                continue
            log.write(f"\n=== {name}: {' '.join(cmd[1:])}\n")
            log.flush()
            exe = shutil.which(cmd[0])
            if not exe:
                log.write(f"{cmd[0]} not found on PATH\n")
                failed.append(name)
                continue
            code = subprocess.run([exe, *cmd[1:]], cwd=cwd, stdout=log, stderr=subprocess.STDOUT).returncode
            log.write(f"=== {name}: exit {code}\n")
            if code:
                failed.append(name)
    status = f"FAILED: {', '.join(failed)}" if failed else "OK"
    if skipped:
        status += f" (skipped: {', '.join(skipped)})"
    (LOGS / "last_run.txt").write_text(f"{started:%Y-%m-%d %H:%M} {status}\n", encoding="utf-8")
    print(status)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
