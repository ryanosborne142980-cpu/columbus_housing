"""Back up the database and copy the file somewhere that survives losing this machine.

SQL Server writes the file itself, as its service account, so it needs a folder that account can
write to and this user can read. The file is verified there, copied to the destination (a OneDrive
folder by default), and the staging copy is removed. See docs/runbook.md for the one-time setup.

COPY_ONLY keeps these backups from affecting any other backup sequence.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

KEEP = 8


def _dir(env: str, parent_env: str, *parts: str) -> Path:
    if value := os.environ.get(env):
        return Path(value)
    if parent := os.environ.get(parent_env):
        return Path(parent, *parts)
    raise ValueError(f"Set {env}: {parent_env} isn't available to build a default.")


def prune(folder: Path, name: str, keep: int = KEEP) -> list[Path]:
    """Delete all but the newest `keep` backups of `name`. Timestamps in names sort by age."""
    # Exact pattern: a plain glob for "columbus_housing_*" would also match columbus_housing_test.
    own = re.compile(re.escape(name) + r"_\d{8}_\d{6}\.bak")
    files = sorted(f for f in folder.iterdir() if own.fullmatch(f.name))
    old = files[:-keep] if keep else files
    for f in old:
        f.unlink()
    return old


def run(con, dest: str | None = None, staging: str | None = None, keep: int = KEEP) -> Path:
    """Back up the connected database. Returns the path of the verified copy at the destination."""
    target = Path(dest) if dest else _dir("COLUMBUS_HOUSING_BACKUP_DIR", "OneDrive", "Backups",
                                          "columbus_housing")
    stage = Path(staging) if staging else _dir("COLUMBUS_HOUSING_BACKUP_STAGING", "LOCALAPPDATA",
                                               "columbus_housing", "backups")
    target.mkdir(parents=True, exist_ok=True)
    name = con.execute("SELECT DB_NAME()").fetchone()[0]
    file = f"{name}_{datetime.now():%Y%m%d_%H%M%S}.bak"
    staged = stage / file

    # BACKUP can't run inside a transaction, and its messages must be drained or it stops early.
    was = con.autocommit
    con.autocommit = True
    try:
        for sql in (f"BACKUP DATABASE [{name}] TO DISK = ? WITH COPY_ONLY, COMPRESSION, CHECKSUM, INIT",
                    "RESTORE VERIFYONLY FROM DISK = ? WITH CHECKSUM"):
            cur = con.execute(sql, str(staged))
            while cur.nextset():
                pass
    finally:
        con.autocommit = was

    size = staged.stat().st_size
    part = target / (file + ".part")
    shutil.copyfile(staged, part)
    if part.stat().st_size != size:
        part.unlink()
        raise OSError(f"Copy to {target} is incomplete; the staging file was kept: {staged}")
    final = part.replace(target / file)
    staged.unlink()
    removed = prune(target, name, keep)
    log.info("backup: %s (%s bytes), removed %s old", final.name, size, len(removed))
    return final
