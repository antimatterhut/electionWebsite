"""HTTP fetch layer: descriptive UA, robots.txt, per-host rate limit, sqlite cache, raw archive (plan §4)."""
from __future__ import annotations

import sqlite3
import time
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import structlog

from .config import ROOT, Settings, load_config

log = structlog.get_logger()

CACHE_DB = ROOT / "data" / "cache" / "http.sqlite"
RAW_DIR = ROOT / "data" / "raw"
ROBOTS_TTL_S = 24 * 3600


class FetchError(RuntimeError):
    """Fetch refused or failed; callers fall back to data/manual."""


class Fetcher:
    def __init__(self, cfg: Settings | None = None, cache_db: Path | None = None, session=None):
        self.cfg = cfg or load_config()
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = self.cfg.http.user_agent
        self.cache_db = Path(cache_db or CACHE_DB)
        self.cache_db.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.cache_db)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS http (url TEXT PRIMARY KEY, etag TEXT, last_modified TEXT,"
            " body BLOB, fetched_at TEXT)"
        )
        self._db.execute("CREATE TABLE IF NOT EXISTS robots (host TEXT PRIMARY KEY, body TEXT, fetched REAL)")
        self._last_hit: dict[str, float] = {}

    # -- robots ---------------------------------------------------------
    def _robots(self, url: str) -> urllib.robotparser.RobotFileParser:
        u = urlparse(url)
        host = f"{u.scheme}://{u.netloc}"
        row = self._db.execute("SELECT body, fetched FROM robots WHERE host=?", (host,)).fetchone()
        if row and time.time() - row[1] < ROBOTS_TTL_S:
            body = row[0]
        else:
            self._throttle(u.netloc)
            try:
                r = self.session.get(f"{host}/robots.txt", timeout=20)
                body = r.text if r.status_code == 200 else ""
            except requests.RequestException:
                body = ""
            self._db.execute("INSERT OR REPLACE INTO robots VALUES (?,?,?)", (host, body, time.time()))
            self._db.commit()
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.splitlines())
        return rp

    def allowed(self, url: str) -> bool:
        return self._robots(url).can_fetch(self.cfg.http.user_agent, url)

    # -- rate limit -----------------------------------------------------
    def _throttle(self, host: str) -> None:
        wait = self._last_hit.get(host, 0.0) + self.cfg.http.min_interval_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    # -- fetch ----------------------------------------------------------
    def get(self, url: str, source: str, params: dict | None = None, archive: bool = True) -> bytes:
        full = requests.Request("GET", url, params=params).prepare().url
        if not self.allowed(full):
            log.warning("source_fetch", source=source, status="robots_disallowed", url=full)
            raise FetchError(f"robots.txt disallows {full}")
        row = self._db.execute("SELECT etag, last_modified, body FROM http WHERE url=?", (full,)).fetchone()
        headers = {}
        if row and row[0]:
            headers["If-None-Match"] = row[0]
        if row and row[1]:
            headers["If-Modified-Since"] = row[1]
        host = urlparse(full).netloc
        last_err: Exception | None = None
        for attempt in range(self.cfg.http.retries):
            self._throttle(host)
            try:
                r = self.session.get(full, headers=headers, timeout=60)
            except requests.RequestException as e:
                last_err = e
            else:
                if r.status_code == 304 and row:
                    return row[2]
                if r.status_code == 200:
                    self._db.execute(
                        "INSERT OR REPLACE INTO http VALUES (?,?,?,?,?)",
                        (full, r.headers.get("ETag"), r.headers.get("Last-Modified"), r.content,
                         datetime.now(timezone.utc).isoformat()),
                    )
                    self._db.commit()
                    if archive:
                        self._archive(source, full, r.content)
                    log.info("source_fetch", source=source, status=200, bytes=len(r.content))
                    return r.content
                if r.status_code not in (429, 500, 502, 503, 504):
                    raise FetchError(f"{full}: HTTP {r.status_code}")
                last_err = FetchError(f"{full}: HTTP {r.status_code}")
            time.sleep(5 * 2**attempt if self.cfg.http.min_interval_s > 0 else 0)
        raise FetchError(f"{full}: retries exhausted ({last_err})")

    def _archive(self, source: str, url: str, body: bytes) -> None:
        d = RAW_DIR / source / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        name = Path(urlparse(url).path).name or "index"
        (d / name).write_bytes(body)

    def close(self) -> None:
        self._db.close()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
