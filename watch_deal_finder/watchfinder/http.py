"""A polite HTTP client: honest User-Agent, random delay between requests,
robots.txt checks, and exponential backoff on 429 / 5xx."""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from .robots import RobotsRules

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
ROBOTS_TTL_SECONDS = 24 * 3600


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class DisallowedByRobots(HttpError):
    pass


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        delay_range: tuple[float, float] = (3.0, 8.0),
        max_retries: int = 3,
        backoff_base: float = 30.0,
        timeout: float = 20.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.user_agent = user_agent
        self.delay_range = delay_range
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.5"})
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, tuple[RobotsRules, float]] = {}

    # -- politeness -------------------------------------------------------

    def _wait_turn(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            wanted = random.uniform(*self.delay_range)
            remaining = wanted - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)

    def robots_for(self, url: str) -> RobotsRules:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots.get(base)
        if cached is None or self._clock() - cached[1] > ROBOTS_TTL_SECONDS:
            rules = RobotsRules("")
            try:
                resp = self._send("GET", base + "/robots.txt", check_robots=False, retry=False)
                if resp.status_code == 200:
                    rules = RobotsRules(resp.text)
                # 4xx (no robots.txt) means everything is allowed; keep the empty rules.
            except HttpError as exc:
                # Can't read robots.txt: be conservative for this run and don't cache,
                # so the next pass tries again.
                log.warning("could not fetch %s/robots.txt (%s); skipping requests to it", base, exc)
                return RobotsRules("User-agent: *\nDisallow: /")
            self._robots[base] = (rules, self._clock())
        return self._robots[base][0]

    # -- requests ---------------------------------------------------------

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self._send("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self._send("POST", url, **kwargs)

    def _send(
        self,
        method: str,
        url: str,
        check_robots: bool = True,
        retry: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        if check_robots and not self.robots_for(url).allowed(url, self.user_agent):
            raise DisallowedByRobots(f"robots.txt disallows {url}")
        host = urlsplit(url).netloc
        kwargs.setdefault("timeout", self.timeout)
        attempts = self.max_retries + 1 if retry else 1
        last_error: str = ""
        for attempt in range(attempts):
            self._wait_turn(host)
            self._last_request[host] = self._clock()
            try:
                resp = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                last_error, status, retry_after = f"{type(exc).__name__}: {exc}", None, None
            else:
                if resp.status_code not in RETRY_STATUSES:
                    return resp
                last_error, status = f"HTTP {resp.status_code}", resp.status_code
                retry_after = _retry_after_seconds(resp)
            if attempt + 1 >= attempts:
                break
            wait = self.backoff_base * (2**attempt)
            if retry_after is not None:
                wait = max(wait, retry_after)
            wait = min(wait, 15 * 60)
            log.warning("%s %s failed (%s); retrying in %.0fs", method, url, last_error, wait)
            self._sleep(wait)
        raise HttpError(f"{method} {url} failed after {attempts} attempt(s): {last_error}", status=status)


def _retry_after_seconds(resp: requests.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if value and value.strip().isdigit():
        return float(value.strip())
    return None
