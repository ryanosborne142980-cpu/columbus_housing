"""Land Zillow's county file in the Databricks volume, unchanged.

Run from the repo root:  python databricks/land_zillow.py

Free Edition restricts outbound internet, so the download runs locally (through pipeline.http,
which applies robots.txt and rate limits) and the file is uploaded as is. The name carries
Zillow's Last-Modified date, so each monthly release is a new file for Auto Loader and an
unchanged release is skipped.
"""
import shutil
import subprocess
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import http, zillow  # noqa: E402

LOCAL = Path("data/landing/zillow_county")
VOLUME = "dbfs:/Volumes/workspace/columbus_housing/raw/zillow_county"
PROFILE = "columbus"


def main() -> int:
    url = zillow.URLS["county"]
    head = http.head(url)
    head.raise_for_status()
    stamp = parsedate_to_datetime(head.headers["Last-Modified"]).date().isoformat()
    path = LOCAL / f"zillow_county_{stamp}.csv"
    if path.exists():
        print(f"{path.name} already landed; nothing to do")
        return 0

    r = http.get(url, timeout=600)
    r.raise_for_status()
    LOCAL.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)

    cli = shutil.which("databricks")
    if not cli:
        print("databricks CLI not on PATH", file=sys.stderr)
        path.unlink()
        return 1
    made = subprocess.run([cli, "fs", "mkdir", VOLUME, "-p", PROFILE])
    done = subprocess.run([cli, "fs", "cp", str(path), f"{VOLUME}/{path.name}", "-p", PROFILE])
    if made.returncode or done.returncode:
        path.unlink()  # so the next run tries again
        return 1
    print(f"landed {path.name} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
