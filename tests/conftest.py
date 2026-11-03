"""Test isolation: every test writes to tmp dirs, never to the repo's data/ tree."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from senate.config import ROOT, load_config


@pytest.fixture
def cfg():
    return load_config(ROOT / "config" / "config.test.yaml")


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """Isolated manual/processed/interim dirs seeded with the repo's real manual tables."""
    manual, proc, interim = tmp_path / "manual", tmp_path / "processed", tmp_path / "interim"
    shutil.copytree(ROOT / "data" / "manual", manual)
    proc.mkdir()
    interim.mkdir()
    monkeypatch.setenv("SENATE_MANUAL_DIR", str(manual))
    monkeypatch.setenv("SENATE_PROCESSED_DIR", str(proc))
    monkeypatch.setenv("SENATE_INTERIM_DIR", str(interim))
    return {"manual": manual, "processed": proc, "interim": interim}


class FakeResponse:
    def __init__(self, status=200, content=b"", text=None, headers=None):
        self.status_code = status
        self.content = content
        self.text = text if text is not None else content.decode("utf-8", "replace")
        self.headers = headers or {}


class FakeSession:
    """requests.Session stand-in: `routes` maps URL substring -> FakeResponse (or callable)."""

    def __init__(self, routes: dict | None = None):
        self.headers: dict = {}
        self.routes = routes or {}
        self.calls: list[str] = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        for key, resp in self.routes.items():
            if key in url:
                return resp() if callable(resp) else resp
        return FakeResponse(404)


@pytest.fixture
def fake_fetcher(cfg, tmp_path):
    from senate.io import Fetcher

    def make(routes):
        return Fetcher(cfg, cache_db=tmp_path / "http.sqlite", session=FakeSession(routes))

    return make


FIXTURES = Path(__file__).parent / "fixtures"
