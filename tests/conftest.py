from datetime import date
from pathlib import Path

import pytest

from scraper.registry import Context

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 16)  # fixtures were captured on this day


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    """Serves fixture files by URL prefix instead of hitting the network."""

    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.calls: list[tuple[str, dict | None]] = []

    def text(self, url, params=None, delay=None):
        self.calls.append((url, params))
        for prefix, name in self.routes.items():
            if url.startswith(prefix):
                return fixture(name)
        raise AssertionError(f"unexpected request {url}")

    def post_text(self, url, data):
        return self.text(url, data)


@pytest.fixture
def make_ctx(tmp_path):
    def make(routes=None):
        return Context(http=FakeHttp(routes or {}), today=TODAY, root=tmp_path)
    return make
