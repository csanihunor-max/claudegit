import pytest
import requests

from watchfinder.http import DisallowedByRobots, HttpClient, HttpError

ROBOTS = "User-agent: *\nDisallow: /private\n"


class Resp:
    def __init__(self, status, text="", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}


class FakeSession:
    def __init__(self, script):
        self.script = script   # url -> list of responses/exceptions, consumed in order
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append(url)
        item = self.script[url].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def client(script, **kw):
    slept = []
    c = HttpClient("TestAgent/1.0", delay_range=(3, 3), session=FakeSession(script), sleep=slept.append,
                   clock=lambda: 0.0, **kw)
    return c, slept


def test_sets_user_agent_and_waits_between_requests():
    c, slept = client({
        "https://s.hu/robots.txt": [Resp(200, ROBOTS)],
        "https://s.hu/a": [Resp(200, "A")],
        "https://s.hu/b": [Resp(200, "B")],
    })
    assert c.session.headers["User-Agent"] == "TestAgent/1.0"
    assert c.get("https://s.hu/a").text == "A"
    assert c.get("https://s.hu/b").text == "B"
    assert slept == [3, 3]   # a pause before each request after the first (robots.txt)


def test_backs_off_on_429_and_5xx_then_succeeds():
    c, slept = client({
        "https://s.hu/robots.txt": [Resp(404)],
        "https://s.hu/a": [Resp(429, headers={"Retry-After": "120"}), Resp(503), Resp(200, "ok")],
    }, backoff_base=30)
    assert c.get("https://s.hu/a").text == "ok"
    waits = [s for s in slept if s != 3]
    assert waits == [120, 60]   # Retry-After honoured, then exponential backoff (30 * 2)


def test_gives_up_after_max_retries():
    c, _ = client({
        "https://s.hu/robots.txt": [Resp(404)],
        "https://s.hu/a": [Resp(500)] * 3,
    }, max_retries=2)
    with pytest.raises(HttpError) as exc:
        c.get("https://s.hu/a")
    assert exc.value.status == 500


def test_connection_errors_are_retried():
    c, _ = client({
        "https://s.hu/robots.txt": [Resp(404)],
        "https://s.hu/a": [requests.ConnectionError("boom"), Resp(200, "ok")],
    })
    assert c.get("https://s.hu/a").text == "ok"


def test_robots_disallow_blocks_request():
    c, _ = client({"https://s.hu/robots.txt": [Resp(200, ROBOTS)]})
    with pytest.raises(DisallowedByRobots):
        c.get("https://s.hu/private/page")
    assert c.session.calls == ["https://s.hu/robots.txt"]


def test_unreachable_robots_txt_means_no_requests_this_time():
    c, _ = client({"https://s.hu/robots.txt": [Resp(503)]})
    with pytest.raises(DisallowedByRobots):
        c.get("https://s.hu/a")


def test_robots_txt_is_refreshed_daily():
    now = [0.0]
    session = FakeSession({
        "https://s.hu/robots.txt": [Resp(200, ""), Resp(200, ROBOTS)],
        "https://s.hu/private/x": [Resp(200, "ok")],
    })
    c = HttpClient("TestAgent/1.0", delay_range=(1, 1), session=session, sleep=lambda s: None, clock=lambda: now[0])
    assert c.get("https://s.hu/private/x").text == "ok"
    now[0] = 25 * 3600
    with pytest.raises(DisallowedByRobots):
        c.get("https://s.hu/private/x")
