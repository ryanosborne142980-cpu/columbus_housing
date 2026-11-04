"""The weekly job: load Franklin, back up, land new rows in Databricks, and run bronze and silver.

Run from anywhere:  python scripts/weekly.py

Every step runs even if an earlier one fails, so a county site outage doesn't also skip the
backup. Output goes to data/logs/, with the outcome in last_run.txt. Exits non-zero if any step
failed, which shows up as the task's last result in Task Scheduler.

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
    ("back up", [PY, "run.py", "backup"], ROOT),
    ("land new rows", [PY, "databricks/land_sql_tables.py"], ROOT),
    ("run pipeline", [PY, "databricks/run_pipeline.py"], ROOT),
]


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    failed = []
    with (LOGS / f"weekly_{started:%Y%m%d_%H%M%S}.log").open("w", encoding="utf-8") as log:
        for name, cmd, cwd in STEPS:
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
    (LOGS / "last_run.txt").write_text(f"{started:%Y-%m-%d %H:%M} {status}\n", encoding="utf-8")
    print(status)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
