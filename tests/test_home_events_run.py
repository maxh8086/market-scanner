"""Tests for fetch_feed (spec 5.2 and 5.4). Offline: no network, no sleeping, no Postgres."""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone

from scanner.home_events import Feed, ParseResult, ParseError, FetchResult, fetch_feed


NOW = datetime(2026, 11, 11, 10, 0, 0, tzinfo=timezone.utc)
FAR_DEADLINE = NOW + timedelta(minutes=10)
CFG = {"gap_min_s": 5, "gap_max_s": 8, "request_timeout_s": 20, "backoff_s": 30}
FEED = Feed(
    feed_code="Financial_Results",
    url="https://example.invalid/feed.xml",
    event_type="filing",
    feed_tier="2",
    default_enabled=True,
    flagged=False,
)
XML_HEADERS = {"Content-Type": "application/xml"}
XML_BODY = b"<rss><channel><item><title>x</title></item></channel></rss>"
HTML_HEADERS = {"Content-Type": "text/html; charset=utf-8"}
HTML_BODY = b"<!doctype html><html><body>blocked</body></html>"
GAP = 6.0  # FakeRng returns this value, so the pre-request sleep is 6.0


class FakeResponse:
    def __init__(self, status_code, headers, content):
        self.status_code = status_code
        self.headers = headers
        self.content = content


class FakeSession:
    """Scripted session. Each get() pops the next item: a response, or an exception to raise."""

    def __init__(self, script, log):
        self._script = list(script)
        self._log = log
        self.calls = []
        self.timeouts = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        self.timeouts.append(timeout)
        self._log.append(("get", url))
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeSleep:
    def __init__(self, log):
        self._log = log
        self.durations = []

    def __call__(self, seconds):
        self.durations.append(seconds)
        self._log.append(("sleep", seconds))


class FakeRng:
    """uniform(a, b) returns `value` when given, otherwise a value from random.Random(seed)."""

    def __init__(self, value=None, seed=7):
        self.value = value
        self._rng = random.Random(seed)
        self.bounds = []

    def uniform(self, a, b):
        self.bounds.append((a, b))
        if self.value is not None:
            return self.value
        return self._rng.uniform(a, b)


class ParseStub:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else ParseResult(items=[{"title": "x"}], dropped=0)
        self.error = error
        self.calls = []

    def __call__(self, feed_code, body):
        self.calls.append((feed_code, body))
        if self.error is not None:
            raise self.error
        return self.result


def xml_ok():
    return FakeResponse(200, dict(XML_HEADERS), XML_BODY)


def run_fetch(script, *, parse_fn=None, rng=None, deadline_at=FAR_DEADLINE):
    log = []
    session = FakeSession(script, log)
    sleep = FakeSleep(log)
    if rng is None:
        rng = FakeRng(value=GAP)
    if parse_fn is None:
        parse_fn = ParseStub()
    result = fetch_feed(
        FEED,
        session=session,
        cfg=CFG,
        parse_fn=parse_fn,
        sleep=sleep,
        rng=rng,
        clock=lambda: NOW,
        deadline_at=deadline_at,
    )
    return result, session, sleep, parse_fn, log


class FetchFeedTests(unittest.TestCase):
    def assert_single_request_no_retry(self, session, sleep):
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleep.durations, [GAP])

    def test_gap_within_bounds(self):
        for seed in (7, 11):
            with self.subTest(seed=seed):
                rng = FakeRng(seed=seed)
                result, session, sleep, parse, log = run_fetch([xml_ok()], rng=rng)
                self.assertEqual(rng.bounds, [(5, 8)])
                gap = sleep.durations[0]
                self.assertTrue(5 <= gap <= 8)
                self.assertEqual(gap, random.Random(seed).uniform(5, 8))
                self.assertEqual(log[0][0], "sleep")
                self.assertEqual(log[1], ("get", FEED.url))
                self.assertEqual(result.outcome, "ok")

    def test_status_500_retries_once_then_continues(self):
        result, session, sleep, parse, log = run_fetch(
            [FakeResponse(500, {}, b"oops"), xml_ok()]
        )
        self.assertEqual(result.outcome, "ok")
        self.assertEqual(result.items, [{"title": "x"}])
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.timeouts, [CFG["request_timeout_s"]] * 2)
        self.assertEqual(sleep.durations, [GAP, CFG["backoff_s"]])
        self.assertEqual(
            log,
            [("sleep", GAP), ("get", FEED.url), ("sleep", 30), ("get", FEED.url)],
        )

    def test_retry_skipped_when_deadline_too_close(self):
        deadline = NOW + timedelta(seconds=49)  # less than backoff 30 + timeout 20
        result, session, sleep, parse, log = run_fetch(
            [FakeResponse(500, {}, b"oops"), xml_ok()], deadline_at=deadline
        )
        self.assertEqual(result.outcome, "transient")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleep.durations, [GAP])

    def test_403_is_blocked_without_retry(self):
        result, session, sleep, parse, log = run_fetch([FakeResponse(403, {}, b"forbidden")])
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.items, [])
        self.assertEqual(result.dropped, 0)
        self.assertEqual(parse.calls, [])
        self.assert_single_request_no_retry(session, sleep)

    def test_html_200_is_blocked(self):
        result, session, sleep, parse, log = run_fetch(
            [FakeResponse(200, dict(HTML_HEADERS), HTML_BODY)]
        )
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.items, [])
        self.assertEqual(result.dropped, 0)
        self.assertEqual(parse.calls, [])
        self.assert_single_request_no_retry(session, sleep)

    def test_empty_200_is_fatal(self):
        result, session, sleep, parse, log = run_fetch(
            [FakeResponse(200, dict(XML_HEADERS), b"")]
        )
        self.assertEqual(result.outcome, "fatal")
        self.assertEqual(result.items, [])
        self.assertEqual(result.dropped, 0)
        self.assertEqual(parse.calls, [])
        self.assert_single_request_no_retry(session, sleep)

    def test_404_is_fatal_without_retry(self):
        result, session, sleep, parse, log = run_fetch([FakeResponse(404, {}, b"not found")])
        self.assertEqual(result.outcome, "fatal")
        self.assertEqual(result.items, [])
        self.assertEqual(result.dropped, 0)
        self.assertIn("404", result.detail)
        self.assertNotIn("example.invalid", result.detail)
        self.assertNotIn("http", result.detail)
        self.assert_single_request_no_retry(session, sleep)

    def test_parse_error_is_fatal(self):
        parse = ParseStub(error=ParseError("bad xml"))
        result, session, sleep, parse, log = run_fetch([xml_ok()], parse_fn=parse)
        self.assertEqual(result.outcome, "fatal")
        self.assertEqual(result.items, [])
        self.assertEqual(result.dropped, 0)
        self.assertEqual(parse.calls, [("Financial_Results", XML_BODY)])
        self.assert_single_request_no_retry(session, sleep)

    def test_timeout_then_second_timeout_is_transient(self):
        result, session, sleep, parse, log = run_fetch(
            [TimeoutError("read timed out"), TimeoutError("read timed out")]
        )
        self.assertEqual(result.outcome, "transient")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(sleep.durations, [GAP, CFG["backoff_s"]])

    def test_ok_returns_parsed_items(self):
        items = [{"title": "Results Q2", "published": "2026-11-10"}]
        parse = ParseStub(result=ParseResult(items=items, dropped=2))
        result, session, sleep, parse, log = run_fetch([xml_ok()], parse_fn=parse)
        self.assertEqual(result, FetchResult(outcome="ok", items=items, dropped=2, detail=""))
        self.assertEqual(parse.calls, [("Financial_Results", XML_BODY)])
        self.assert_single_request_no_retry(session, sleep)


if __name__ == "__main__":
    unittest.main()
