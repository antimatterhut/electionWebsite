import pytest

from senate.io import FetchError
from tests.conftest import FakeResponse

ROBOTS = "User-agent: *\nDisallow: /private\n"


def test_robots_disallow_refuses_fetch(fake_fetcher):
    f = fake_fetcher({"robots.txt": FakeResponse(200, text=ROBOTS),
                      "/private": FakeResponse(200, b"secret")})
    with pytest.raises(FetchError, match="robots"):
        f.get("https://example.org/private/x", "t")
    assert not any("/private/x" in c for c in f.session.calls)


def test_fetch_caches_body_and_sends_user_agent(fake_fetcher, cfg):
    f = fake_fetcher({"robots.txt": FakeResponse(200, text=""), "/data": FakeResponse(200, b"abc", headers={"ETag": "x"})})
    assert f.get("https://example.org/data", "t", archive=False) == b"abc"
    assert f.session.headers["User-Agent"] == cfg.http.user_agent
    assert "SenateCountyProjection" in f.session.headers["User-Agent"]


def test_304_returns_cached_body(fake_fetcher):
    state = {"n": 0}

    def data():
        state["n"] += 1
        return FakeResponse(200, b"v1", headers={"ETag": "e1"}) if state["n"] == 1 else FakeResponse(304)

    f = fake_fetcher({"robots.txt": FakeResponse(200, text=""), "/data": data})
    assert f.get("https://example.org/data", "t", archive=False) == b"v1"
    assert f.get("https://example.org/data", "t", archive=False) == b"v1"


def test_retries_on_5xx_then_fails(fake_fetcher):
    f = fake_fetcher({"robots.txt": FakeResponse(200, text=""), "/data": FakeResponse(503)})
    with pytest.raises(FetchError, match="retries exhausted"):
        f.get("https://example.org/data", "t", archive=False)
    assert sum("/data" in c for c in f.session.calls) == 4  # http.retries


def test_4xx_fails_immediately(fake_fetcher):
    f = fake_fetcher({"robots.txt": FakeResponse(200, text=""), "/data": FakeResponse(404)})
    with pytest.raises(FetchError, match="404"):
        f.get("https://example.org/data", "t", archive=False)
    assert sum("/data" in c for c in f.session.calls) == 1
