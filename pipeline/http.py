"""Polite HTTP: identifies itself, honors robots.txt (incl. Crawl-delay), rate-limits per host,
and backs off when a server says to (429/503 + Retry-After).

Not handled: redirects are followed by requests without re-checking robots.txt or throttling
the target host. Current sources (Franklin auditor pages, Redfin S3) don't redirect cross-host.
"""
from __future__ import annotations

import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = "columbus-housing-pipeline/1.0 (personal research; contact via GitHub)"
MIN_INTERVAL_SEC = 2.0
MAX_RETRIES = 3          # extra attempts after a 429/503
MAX_BACKOFF_SEC = 300.0  # cap on any single wait, including a server's Retry-After

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}
_last_hit: dict[str, float] = {}


class RobotsDisallowed(RuntimeError):
    pass


def _throttle(host: str, interval: float) -> None:
    # Wait until `interval` seconds have passed since the last request to this host.
    wait = interval - (time.monotonic() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def _robots_for(url: str) -> urllib.robotparser.RobotFileParser:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        _throttle(p.netloc, MIN_INTERVAL_SEC)
        # Network errors propagate: if robots.txt is unreachable, so is the site.
        r = _session.get(f"{base}/robots.txt", timeout=20)
        if r.status_code >= 500:
            # Server trouble: refuse for now, but don't cache, so a later call can retry.
            raise RobotsDisallowed(f"robots.txt returned HTTP {r.status_code} for {base}")
        if r.status_code in (401, 403):
            rp.disallow_all = True  # being blocked; same rule as RobotFileParser.read()
        else:
            rp.parse(r.text.splitlines() if r.ok else [])  # 404 etc. -> no rules, allow
        _robots[base] = rp
    return _robots[base]


def _retry_after(r: requests.Response, attempt: int) -> float:
    # Server's Retry-After in seconds if given (HTTP-date form falls back), else exponential.
    try:
        wait = float(r.headers.get("Retry-After", ""))
    except ValueError:
        wait = 5.0 * 2 ** attempt
    return min(max(wait, 0.0), MAX_BACKOFF_SEC)


def get(url: str, *, timeout: int = 60, check_robots: bool = True) -> requests.Response:
    """GET with robots, throttle and backoff. Returns any final status (callers check it:
    discovery relies on 404s coming back as responses)."""
    return _request("GET", url, timeout, check_robots)


def head(url: str, *, timeout: int = 60, check_robots: bool = True) -> requests.Response:
    """HEAD with the same rules as get(); use to check Last-Modified before a big download."""
    return _request("HEAD", url, timeout, check_robots)


def _request(method: str, url: str, timeout: int, check_robots: bool) -> requests.Response:
    interval = MIN_INTERVAL_SEC
    if check_robots:
        rp = _robots_for(url)
        if not rp.can_fetch(USER_AGENT, url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        interval = max(interval, float(rp.crawl_delay(USER_AGENT) or 0))
    host = urlparse(url).netloc
    for attempt in range(MAX_RETRIES + 1):
        _throttle(host, interval)
        r = _session.request(method, url, timeout=timeout)
        if r.status_code not in (429, 503) or attempt == MAX_RETRIES:
            return r
        time.sleep(_retry_after(r, attempt))
    return r
