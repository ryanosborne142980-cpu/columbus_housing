"""Polite HTTP: identifies itself, honors robots.txt, rate-limits per host."""
from __future__ import annotations

import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = "columbus-housing-pipeline/1.0 (personal research; contact via GitHub)"
MIN_INTERVAL_SEC = 2.0

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}
_last_hit: dict[str, float] = {}


class RobotsDisallowed(RuntimeError):
    pass


def _robots_for(url: str) -> urllib.robotparser.RobotFileParser:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = _session.get(f"{base}/robots.txt", timeout=20)
            rp.parse(r.text.splitlines() if r.ok else [])
        except requests.RequestException:
            rp.parse([])  # unreachable robots.txt -> treat as allow-all
        _robots[base] = rp
    return _robots[base]


def get(url: str, *, timeout: int = 60, stream: bool = False, check_robots: bool = True) -> requests.Response:
    if check_robots and not _robots_for(url).can_fetch(USER_AGENT, url):
        raise RobotsDisallowed(f"robots.txt disallows {url}")
    host = urlparse(url).netloc
    wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    r = _session.get(url, timeout=timeout, stream=stream)
    _last_hit[host] = time.monotonic()
    return r
