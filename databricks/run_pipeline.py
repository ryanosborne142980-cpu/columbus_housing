"""Run the pipeline and report how it really ended.

Run from the repo root:  python databricks/run_pipeline.py [target]

When Auto Loader meets a new column, the update stops and `bundle run` exits 1, but the pipeline starts
a new update by itself with cause SCHEMA_CHANGE. So a non-zero exit doesn't mean failure. This waits for
any restart to finish and exits 0 only if the newest update, started after this run began, completed.
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = {"dev": "columbus_housing_bronze", "test": "columbus_housing_test_bronze"}
FINISHED = {"COMPLETED", "FAILED", "CANCELED"}
POLL_SECONDS = 20
QUIET_POLLS = 3  # a finished update has to stay newest this long, in case a restart is about to start
MAX_POLLS = 60  # counted, not timed: a laptop that sleeps mid-wait shouldn't use up the time


def _json(*args):
    cli = shutil.which("databricks")
    r = subprocess.run([cli, *args, "-p", "columbus", "-o", "json"], capture_output=True, text=True,
                       encoding="utf-8", check=True)
    start = min(i for i in (r.stdout.find("{"), r.stdout.find("[")) if i >= 0)
    return json.loads(r.stdout[start:])


def _updates(pipeline_id):
    return _json("pipelines", "list-updates", pipeline_id).get("updates", [])


def run(target: str = "dev") -> int:
    cli = shutil.which("databricks")
    if not cli:
        print("databricks CLI not on PATH", file=sys.stderr)
        return 1
    pipeline_id = next(p["pipeline_id"] for p in _json("pipelines", "list-pipelines")
                       if p["name"] == NAMES[target])
    before = {u["update_id"] for u in _updates(pipeline_id)}

    command = [cli, "bundle", "run", "bronze", "-t", target, "-p", "columbus"]
    code = subprocess.run(command, cwd=HERE).returncode
    if code == 0:
        return 0

    print(f"bundle run exited {code}; checking whether the pipeline restarted itself")
    quiet = 0
    for _ in range(MAX_POLLS):
        try:
            newest = _updates(pipeline_id)[0]
        except subprocess.CalledProcessError:  # e.g. no network yet after the laptop wakes
            time.sleep(POLL_SECONDS)
            continue
        if newest["update_id"] not in before and newest.get("state") in FINISHED:
            quiet += 1
            if quiet >= QUIET_POLLS:
                print(f"newest update {newest['state']} (cause {newest.get('cause')})")
                return 0 if newest["state"] == "COMPLETED" else 1
        else:
            quiet = 0
        time.sleep(POLL_SECONDS)
    print("timed out waiting for the pipeline to settle", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(run(*sys.argv[1:2]))
