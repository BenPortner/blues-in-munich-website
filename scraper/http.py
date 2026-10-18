"""Polite HTTP client shared by all adapters."""
from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_REPO = os.environ.get("GITHUB_REPOSITORY")
USER_AGENT = "BluesInMunichBot/1.0 (daily blues event listing; +https://www.bluesinmunich.de{})".format(
    f"; +https://github.com/{_REPO}" if _REPO else "")


class Http:
    def __init__(self, delay: float = 1.0, timeout: float = 30.0):
        self.delay = delay
        self.timeout = timeout
        self._last_hit: dict[str, float] = {}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "de,en;q=0.8"})
        retry = Retry(total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def _wait(self, url: str, delay: float | None = None) -> None:
        host = urlparse(url).netloc
        delay = self.delay if delay is None else max(delay, self.delay)
        elapsed = time.monotonic() - self._last_hit.get(host, 0.0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str, params: dict | None = None, delay: float | None = None) -> requests.Response:
        """`delay` raises the pause between hits on this host (e.g. a robots.txt Crawl-delay)."""
        self._wait(url, delay)
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp

    def text(self, url: str, params: dict | None = None, delay: float | None = None) -> str:
        resp = self.get(url, params, delay)
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        return resp.text

    def json(self, url: str, params: dict | None = None):
        return self.get(url, params).json()
