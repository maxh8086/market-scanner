"""Tests for fetch_feed (spec 5.2 and 5.4). Offline: no network, no sleeping, no Postgres."""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone

from scanner import home_events
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

    def test_429_is_blocked_without_retry(self):
        result, session, sleep, parse, log = run_fetch([FakeResponse(429, {}, b"slow down")])
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


FEED_FIN = Feed(
    feed_code="nse:Financial_Results",
    url="https://example.invalid/fin.xml",
    event_type="filing",
    feed_tier="2",
    default_enabled=True,
    flagged=False,
)
FEED_ANN = Feed(
    feed_code="nse:Corporate_Announcements",
    url="https://example.invalid/ann.xml",
    event_type="filing",
    feed_tier="2",
    default_enabled=True,
    flagged=False,
)
FEED_BOARD = Feed(
    feed_code="nse:Board_Meetings",
    url="https://example.invalid/board.xml",
    event_type="filing",
    feed_tier="2",
    default_enabled=True,
    flagged=False,
)
ONE_FEED = (FEED_FIN,)
TWO_FEEDS = (FEED_FIN, FEED_ANN)
THREE_FEEDS = (FEED_FIN, FEED_ANN, FEED_BOARD)
UNIVERSE = {"RELIANCE": "INE002A01018", "TCS": "INE467B01029"}
PUB_EARLY = datetime(2026, 11, 10, 9, 0, 0, tzinfo=timezone.utc)
PUB_LATE = datetime(2026, 11, 11, 8, 30, 0, tzinfo=timezone.utc)


class FakeCooldown:
    """Injected Cooldown. active() pops the next scripted value and then keeps the last one."""

    def __init__(self, active_values=(False,)):
        self._values = list(active_values)
        self.active_calls = []
        self.blocks = []
        self.resets = []

    def active(self, exchange, now):
        self.active_calls.append((exchange, now))
        if len(self._values) > 1:
            return self._values.pop(0)
        return self._values[0]

    def block(self, exchange, now, reason):
        self.blocks.append((exchange, now, reason))

    def reset(self, exchange):
        self.resets.append(exchange)


class FakeClock:
    """Simulated time. AdvancingSleep moves it forward, so nothing waits for real."""

    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class AdvancingSleep(FakeSleep):
    """FakeSleep that also moves the fake clock forward by the slept seconds."""

    def __init__(self, log, clock):
        super().__init__(log)
        self._clock = clock

    def __call__(self, seconds):
        super().__call__(seconds)
        self._clock.now += timedelta(seconds=seconds)


class FakePost:
    """Injected post. Records each batch; returns inserted=len(rows), or raises `error`."""

    def __init__(self, error=None, invalid=0):
        self.error = error
        self.invalid = invalid
        self.calls = []

    def __call__(self, rows):
        self.calls.append(list(rows))
        if self.error is not None:
            raise self.error
        return {"inserted": len(rows), "duplicates": 0, "invalid": self.invalid}


def make_item(symbol, published_at=PUB_EARLY, url_tag="a"):
    return {
        "symbol": symbol,
        "company": f"{symbol} Ltd",
        "headline": f"{symbol} filing",
        "title": "Example Ltd",
        "description": "RELATING TO:First Quarter |AUDITED/UNAUDITED:Unaudited",
        "source_id": None,
        "source_url": f"https://example.invalid/{url_tag}",
        "published_at": published_at,
    }


def posted_rows(post):
    return [row for batch in post.calls for row in batch]


def as_datetime(value):
    """from and to may be datetimes or ISO strings (spec 5.1 does not fix the type)."""
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def run_cycle_with(
    script,
    *,
    feeds=THREE_FEEDS,
    params=None,
    now=NOW,
    parse_fn=None,
    post=None,
    cooldown=None,
    rng=None,
    by_name=None,
):
    log = []
    session = FakeSession(script, log)
    clock = FakeClock(NOW)
    sleep = AdvancingSleep(log, clock)
    if rng is None:
        rng = FakeRng(value=GAP)
    if parse_fn is None:
        parse_fn = ParseStub(result=ParseResult(items=[make_item("RELIANCE")], dropped=0))
    if post is None:
        post = FakePost()
    if cooldown is None:
        cooldown = FakeCooldown()
    result = home_events.run_cycle(
        {} if params is None else params,
        now,
        feeds=feeds,
        parse_fn=parse_fn,
        universe=UNIVERSE,
        session=session,
        post=post,
        sleep=sleep,
        rng=rng,
        clock=clock,
        cooldown=cooldown,
        by_name=by_name,
    )
    return result, session, sleep, post, cooldown


class RunCycleTests(unittest.TestCase):
    def test_cooldown_active_skipped_zero_requests(self):
        cooldown = FakeCooldown(active_values=(True,))
        result, session, sleep, post, cooldown = run_cycle_with([], cooldown=cooldown)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["message"], "exchange_cooldown")
        self.assertEqual(session.calls, [])
        self.assertEqual(sleep.durations, [])
        self.assertEqual(post.calls, [])
        self.assertEqual(cooldown.blocks, [])
        self.assertEqual(cooldown.resets, [])
        self.assertEqual(cooldown.active_calls[0][0], "nse")

    def test_block_on_third_feed_failed_and_cooldown_blocked(self):
        script = [xml_ok(), xml_ok(), FakeResponse(403, {}, b"forbidden")]
        result, session, sleep, post, cooldown = run_cycle_with(script)
        self.assertEqual(result["status"], "failed")
        self.assertIn("blocked:nse:Board_Meetings", result["message"])
        self.assertEqual(len(cooldown.blocks), 1)
        exchange, _, reason = cooldown.blocks[0]
        self.assertEqual(exchange, "nse")
        self.assertEqual(reason, "blocked:nse:Board_Meetings")
        self.assertEqual(cooldown.resets, [])
        self.assertEqual(len(session.calls), 3)  # a 403 is not retried
        self.assertEqual(result["fetched"], 2)
        self.assertEqual(len(posted_rows(post)), 2)  # the two feeds before the block are posted

    def test_429_on_third_feed_failed_and_cooldown_blocked(self):
        script = [xml_ok(), xml_ok(), FakeResponse(429, {}, b"slow down")]
        result, session, sleep, post, cooldown = run_cycle_with(script)
        self.assertEqual(result["status"], "failed")
        self.assertIn("blocked:nse:Board_Meetings", result["message"])
        self.assertEqual(len(cooldown.blocks), 1)
        exchange, _, reason = cooldown.blocks[0]
        self.assertEqual(exchange, "nse")
        self.assertEqual(reason, "blocked:nse:Board_Meetings")
        self.assertEqual(cooldown.resets, [])
        self.assertEqual(len(session.calls), 3)  # a 429 is not retried
        self.assertEqual(result["fetched"], 2)
        self.assertEqual(len(posted_rows(post)), 2)  # the two feeds before the block are posted

    def test_success_then_block_twice_never_resets(self):
        # A run stops at its first block, so "block twice" is two runs sharing one cooldown.
        cooldown = FakeCooldown()
        results = []
        for _ in range(2):
            result, session, sleep, post, cooldown = run_cycle_with(
                [xml_ok(), FakeResponse(403, {}, b"forbidden")],
                feeds=TWO_FEEDS,
                cooldown=cooldown,
            )
            results.append(result)
        for result in results:
            self.assertEqual(result["status"], "failed")
            self.assertIn("blocked:nse:Corporate_Announcements", result["message"])
        self.assertEqual(len(cooldown.blocks), 2)
        self.assertEqual(cooldown.resets, [])

    def test_reset_called_once_after_block_free_run(self):
        result, session, sleep, post, cooldown = run_cycle_with([xml_ok(), xml_ok(), xml_ok()])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(cooldown.blocks, [])
        self.assertEqual(cooldown.resets, ["nse"])

    def test_reset_skipped_when_cooldown_seen_mid_run(self):
        # active() is read once at the start and once before each feed (spec 5.1 steps 2 and 4b).
        cooldown = FakeCooldown(active_values=(False, False, True))
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok(), xml_ok(), xml_ok()], cooldown=cooldown
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("exchange_cooldown", result["message"])
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(result["fetched"], 1)
        self.assertEqual(cooldown.blocks, [])
        self.assertEqual(cooldown.resets, [])

    def test_status_500_retries_once_then_continues(self):
        script = [FakeResponse(500, {}, b"oops"), xml_ok(), xml_ok()]
        result, session, sleep, post, cooldown = run_cycle_with(script, feeds=TWO_FEEDS)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sleep.durations, [GAP, 30, GAP])  # gap, backoff, then the second feed's gap
        self.assertEqual(result["fetched"], 2)

    def test_retry_skipped_when_deadline_too_close(self):
        # run_deadline_s 49: after the 6 s gap, 43 s remain, but a retry needs backoff 30 + timeout 20.
        script = [FakeResponse(500, {}, b"oops"), xml_ok()]
        result, session, sleep, post, cooldown = run_cycle_with(
            script, feeds=ONE_FEED, params={"run_deadline_s": 49}
        )
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleep.durations, [GAP])
        self.assertEqual(result["fetched"], 0)

    def test_deadline_stops_loop_ok_with_message(self):
        # run_deadline_s 30: feed 1 is started (8 + 20 <= 30), then the 6 s gap leaves
        # feed 2 needing 6 + 8 + 20 = 34 s, which is past the deadline.
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], params={"run_deadline_s": 30}
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("deadline: 2 feeds not fetched", result["message"])
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(cooldown.resets, ["nse"])

    def test_deadline_zero_feeds_failed(self):
        result, session, sleep, post, cooldown = run_cycle_with(
            [], params={"run_deadline_s": 10}
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("deadline: 0 feeds fetched", result["message"])
        self.assertEqual(session.calls, [])
        self.assertEqual(cooldown.resets, [])

    def test_all_feeds_fail_failed(self):
        # Each feed: 500, one retry, 500 again, which is transient. Both feeds fail.
        script = [FakeResponse(500, {}, b"oops") for _ in range(4)]
        result, session, sleep, post, cooldown = run_cycle_with(script, feeds=TWO_FEEDS)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["fetched"], 0)
        self.assertEqual(len(session.calls), 4)
        self.assertEqual(posted_rows(post), [])

    def test_non_transient_feed_failure_marks_failed(self):
        script = [xml_ok(), FakeResponse(404, {}, b"not found")]
        result, session, sleep, post, cooldown = run_cycle_with(script, feeds=TWO_FEEDS)
        self.assertEqual(result["status"], "failed")
        self.assertIn("nse:Corporate_Announcements", result["message"])
        self.assertEqual(result["fetched"], 1)

    def test_transient_failure_ok_with_message(self):
        script = [xml_ok(), FakeResponse(500, {}, b"oops"), FakeResponse(500, {}, b"oops")]
        result, session, sleep, post, cooldown = run_cycle_with(script, feeds=TWO_FEEDS)
        self.assertEqual(result["status"], "ok")
        self.assertIn("failed:nse:Corporate_Announcements", result["message"])
        self.assertEqual(result["fetched"], 1)

    def test_rejected_counts_in_message(self):
        parsed = ParseResult(
            items=[make_item("RELIANCE"), make_item("INFY", url_tag="b"), make_item("WIPRO", url_tag="c")],
            dropped=1,
        )
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, parse_fn=ParseStub(result=parsed)
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("rejected parse=1 universe=2", result["message"])
        self.assertIn("invalid=0", result["message"])

    def test_gap_within_bounds_seeded(self):
        rng = FakeRng(seed=7)
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok(), xml_ok(), xml_ok()], rng=rng
        )
        self.assertEqual(rng.bounds, [(5, 8)] * 3)
        expected = random.Random(7)
        self.assertEqual(sleep.durations, [expected.uniform(5, 8) for _ in range(3)])
        for gap in sleep.durations:
            self.assertTrue(5 <= gap <= 8)
        self.assertEqual(len(session.calls), 3)

    def test_name_only_items_resolve_through_by_name(self):
        named = dict(make_item("X", PUB_EARLY, "a"), symbol=None, company="Reliance Limited")
        unknown = dict(make_item("Y", PUB_LATE, "b"), symbol=None, company="Nobody Ltd")
        parsed = ParseResult(items=[named, unknown], dropped=0)
        by_name = {"RELIANCE LTD": ("RELIANCE", UNIVERSE["RELIANCE"])}
        result, _session, _sleep, post, _cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, parse_fn=ParseStub(result=parsed), by_name=by_name
        )
        self.assertEqual(result["status"], "ok")
        rows = posted_rows(post)
        self.assertEqual([row["isin"] for row in rows], [UNIVERSE["RELIANCE"]])
        self.assertIn("universe=1", result["message"])

    def test_name_resolved_item_with_disagreeing_isin_is_rejected(self):
        # The name maps to RELIANCE with ISIN_A, but the item supplies a different ISIN_B.
        # fill_from_name leaves it unresolved (symbol None), so filter_items counts it under
        # "universe", and count_isin_conflicts records the reason as isin_conflict=1.
        named = dict(make_item("X", PUB_EARLY, "a"), symbol=None, company="Reliance Limited", isin="INE999Z01099")
        parsed = ParseResult(items=[named], dropped=0)
        by_name = {"RELIANCE LTD": ("RELIANCE", UNIVERSE["RELIANCE"])}
        result, _session, _sleep, post, _cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, parse_fn=ParseStub(result=parsed), by_name=by_name
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(posted_rows(post), [])
        self.assertIn("universe=1", result["message"])
        self.assertIn("isin_conflict=1", result["message"])

    def test_rows_go_to_post(self):
        parsed = ParseResult(
            items=[make_item("RELIANCE", PUB_EARLY, "a"), make_item("TCS", PUB_LATE, "b")],
            dropped=0,
        )
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, parse_fn=ParseStub(result=parsed)
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(set(result), {"status", "fetched", "new", "from", "to", "message"})
        self.assertEqual(len(post.calls), 1)
        rows = posted_rows(post)
        self.assertEqual([row["isin"] for row in rows], [UNIVERSE["RELIANCE"], UNIVERSE["TCS"]])
        for row in rows:
            self.assertEqual(row["feed_code"], FEED_FIN.feed_code)
            self.assertEqual(row["exchange"], "NSE")
            self.assertTrue(row["dedupe_key"].startswith(FEED_FIN.feed_code + ":"))
        self.assertEqual(result["fetched"], 2)
        self.assertEqual(result["new"], 2)
        self.assertEqual(as_datetime(result["from"]), PUB_EARLY)
        self.assertEqual(as_datetime(result["to"]), PUB_LATE)

    def test_invalid_rows_mark_failed(self):
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, post=FakePost(invalid=2)
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("invalid:2", result["message"])

    def test_bad_config_failed(self):
        cases = (
            ({"request_timeout_s": -1}, "config:request_timeout_s"),
            ({"gap_min_s": 9, "gap_max_s": 8}, "config:"),
        )
        for params, expected in cases:
            with self.subTest(params=params):
                result, session, sleep, post, cooldown = run_cycle_with([], params=params)
                self.assertEqual(result["status"], "failed")
                self.assertIn(expected, result["message"])
                self.assertEqual(session.calls, [])
                self.assertEqual(sleep.durations, [])
                self.assertEqual(post.calls, [])
                self.assertEqual(cooldown.active_calls, [])  # validation runs before the cooldown read

    def test_post_failure_stops_loop_api_error_no_cooldown_change(self):
        post = FakePost(error=RuntimeError("api status 500"))
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok(), xml_ok(), xml_ok()], post=post
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("api_error", result["message"])
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(cooldown.blocks, [])
        self.assertEqual(cooldown.resets, [])

    def test_start_feed_rotates(self):
        # start index = int(now.timestamp() // 300) % 3: NOW gives 0, NOW + 300 s gives 1, NOW + 600 s gives 2.
        cases = (
            (NOW + timedelta(seconds=300), [FEED_ANN, FEED_BOARD, FEED_FIN]),
            (NOW + timedelta(seconds=600), [FEED_BOARD, FEED_FIN, FEED_ANN]),
        )
        for now, order in cases:
            with self.subTest(now=now.isoformat()):
                result, session, sleep, post, cooldown = run_cycle_with(
                    [xml_ok(), xml_ok(), xml_ok()], now=now
                )
                self.assertEqual(session.calls, [feed.url for feed in order])


class _PostOkThenRaise:
    """Injected post for the hardening tests. Call 1 succeeds (inserted=len(rows)); later calls raise."""

    def __init__(self):
        self.calls = []
        self.responses = []

    def __call__(self, rows):
        self.calls.append(list(rows))
        if len(self.calls) == 1:
            response = {"inserted": len(rows), "duplicates": 0, "invalid": 0}
            self.responses.append(response)
            return response
        raise RuntimeError("api status 500")


class _ParseFirstThenLater:
    """Injected parse_fn for the hardening tests. Call 1 returns `first`; later calls return `later`."""

    def __init__(self, first, later):
        self.first = first
        self.later = later
        self.calls = []

    def __call__(self, feed_code, body):
        self.calls.append((feed_code, body))
        return self.first if len(self.calls) == 1 else self.later


class RunCycleHardeningTests(unittest.TestCase):
    def test_duplicate_keys_in_one_batch_posted_once(self):
        # Same feed_code, source_url and published_at give the same dedupe_key (spec 4.2).
        parsed = ParseResult(
            items=[
                make_item("RELIANCE", PUB_EARLY, "a"),
                make_item("RELIANCE", PUB_EARLY, "a"),
                make_item("TCS", PUB_LATE, "b"),
            ],
            dropped=0,
        )
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, parse_fn=ParseStub(result=parsed)
        )
        self.assertEqual(len(post.calls), 1)
        rows = posted_rows(post)
        self.assertEqual(len(rows), 2)
        keys = [row["dedupe_key"] for row in rows]
        self.assertEqual(len(set(keys)), len(keys))

    def test_huge_int_param_is_config_error(self):
        result, session, sleep, post, cooldown = run_cycle_with(
            [], params={"gap_min_s": 10**400, "gap_max_s": 8}
        )
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["message"].startswith("config:"))
        self.assertEqual(session.calls, [])

    def test_finite_huge_run_deadline_is_config_error(self):
        # 10**12 is finite and positive, so it passes validation. clock() + 10**12 s overflows datetime.
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, params={"run_deadline_s": 10**12}
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["message"], "config:run_deadline_s")
        self.assertEqual(session.calls, [])

    def test_finite_huge_gap_max_is_config_error(self):
        # 10**12 is finite and positive, so it passes validation. clock() + per-feed budget overflows datetime.
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, params={"gap_max_s": 10**12}
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["message"], "config:gap_max_s")

    def test_finite_huge_backoff_skips_retry_without_raising(self):
        # The first response is transient. The retry would need clock() + 10**12 s, which overflows datetime,
        # so the retry must be skipped instead of raising.
        script = [FakeResponse(500, {}, b"oops"), xml_ok()]
        result, session, sleep, post, cooldown = run_cycle_with(
            script, feeds=ONE_FEED, params={"backoff_s": 10**12}
        )
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn(10**12, sleep.durations)
        self.assertFalse(result.get("message", "").startswith("config:"))

    def test_invalid_rows_stop_loop_and_reset_per_spec(self):
        # Invalid rows end the run (spec 5.2). Reset still happens: no block, no mid-run cooldown,
        # and one feed succeeded (spec 5.1 step 5). Invalid is not excluded from that rule.
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok(), xml_ok(), xml_ok()], post=FakePost(invalid=2)
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("invalid:2", result["message"])
        self.assertEqual(len(post.calls), 1)
        self.assertEqual(cooldown.resets, ["nse"])

    def test_post_failure_on_later_feed_keeps_first_feed_counts(self):
        parsed = ParseResult(
            items=[make_item("RELIANCE", PUB_EARLY, "a"), make_item("TCS", PUB_LATE, "b")],
            dropped=0,
        )
        # Feed 2 has later times. They must not reach from/to, because its post raised.
        parsed_later = ParseResult(
            items=[
                make_item("RELIANCE", PUB_LATE + timedelta(days=1), "c"),
                make_item("TCS", PUB_LATE + timedelta(days=1), "d"),
            ],
            dropped=0,
        )
        post = _PostOkThenRaise()
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok(), xml_ok(), xml_ok()],
            parse_fn=_ParseFirstThenLater(parsed, parsed_later),
            post=post,
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["message"], "api_error")
        self.assertEqual(len(post.calls), 2)
        self.assertEqual(result["new"], post.responses[0]["inserted"])
        first_feed_times = [as_datetime(row["published_at"]) for row in post.calls[0]]
        self.assertEqual(as_datetime(result["from"]), min(first_feed_times))
        self.assertEqual(as_datetime(result["to"]), max(first_feed_times))
        self.assertEqual(cooldown.resets, [])

    def test_all_rows_rejected_gives_none_bounds(self):
        # None of the parsed symbols is in UNIVERSE, so every feed posts an empty batch (spec 5.1 step 4f).
        parsed = ParseResult(
            items=[make_item("INFY", PUB_EARLY, "a"), make_item("WIPRO", PUB_LATE, "b")],
            dropped=0,
        )
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok(), xml_ok(), xml_ok()], parse_fn=ParseStub(result=parsed)
        )
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["from"])
        self.assertIsNone(result["to"])
        self.assertEqual(len(post.calls), 3)
        self.assertEqual(post.calls, [[], [], []])

    def test_deadline_exactly_gap_plus_timeout_starts_feed(self):
        # The check stops only when clock() + gap_max_s + request_timeout_s > deadline_at, so equality starts the feed.
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()],
            feeds=ONE_FEED,
            params={"gap_max_s": 8, "request_timeout_s": 20, "run_deadline_s": 28},
        )
        self.assertGreaterEqual(len(session.calls), 1)

    def test_deadline_just_below_gap_plus_timeout_starts_no_feed(self):
        result, session, sleep, post, cooldown = run_cycle_with(
            [],
            feeds=ONE_FEED,
            params={"gap_max_s": 8, "request_timeout_s": 20, "run_deadline_s": 27.9},
        )
        self.assertEqual(session.calls, [])
        self.assertEqual(result["status"], "failed")
        self.assertIn("deadline: 0 feeds fetched", result["message"])

    def test_bool_and_nan_params_are_config_errors(self):
        cases = (
            ({"gap_min_s": True}, "config:gap_min_s"),
            ({"request_timeout_s": float("nan")}, "config:request_timeout_s"),
        )
        for params, expected in cases:
            with self.subTest(params=params):
                result, session, sleep, post, cooldown = run_cycle_with([], params=params)
                self.assertEqual(result["status"], "failed")
                self.assertTrue(result["message"].startswith(expected))
                self.assertEqual(session.calls, [])


class IngestFloorTests(unittest.TestCase):
    """Ingest age floor (decision D8): items older than ingest_floor_days are dropped before filter_items."""

    CUTOFF = NOW - timedelta(days=730)

    def test_item_exactly_on_cutoff_is_kept(self):
        parsed = ParseResult(
            items=[make_item("RELIANCE", self.CUTOFF, "a")], dropped=0,
        )
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, parse_fn=ParseStub(result=parsed),
        )
        self.assertEqual(result["status"], "ok")
        rows = posted_rows(post)
        self.assertEqual(len(rows), 1)
        self.assertEqual(as_datetime(rows[0]["published_at"]), self.CUTOFF)
        self.assertIn("date_floor=0", result["message"])

    def test_older_item_dropped_and_counted_as_date_floor(self):
        parsed = ParseResult(
            items=[
                make_item("RELIANCE", self.CUTOFF, "a"),
                make_item("TCS", self.CUTOFF - timedelta(seconds=1), "b"),
            ],
            dropped=0,
        )
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, parse_fn=ParseStub(result=parsed),
        )
        self.assertEqual(result["status"], "ok")
        rows = posted_rows(post)
        self.assertEqual([row["published_at"] for row in rows], [self.CUTOFF.isoformat()])
        self.assertIn("date_floor=1", result["message"])
        self.assertIn("universe=0", result["message"])

    def test_all_items_below_floor_run_completes_nothing_posted(self):
        parsed = ParseResult(
            items=[
                make_item("RELIANCE", self.CUTOFF - timedelta(days=1), "a"),
                make_item("TCS", self.CUTOFF - timedelta(days=400), "b"),
            ],
            dropped=0,
        )
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, parse_fn=ParseStub(result=parsed),
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(posted_rows(post), [])
        self.assertEqual(result["new"], 0)
        self.assertIsNone(result["from"])
        self.assertIn("date_floor=2", result["message"])

    def test_custom_floor_days_moves_the_cutoff(self):
        parsed = ParseResult(items=[make_item("RELIANCE", PUB_EARLY, "a")], dropped=0)
        # The cutoff is NOW - 1 day = 2026-11-10 10:00 UTC. PUB_EARLY (2026-11-10 09:00 UTC) is
        # one hour before it, so the 1-day floor drops it.
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, parse_fn=ParseStub(result=parsed),
            params={"ingest_floor_days": 1},
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("date_floor=1", result["message"])
        self.assertEqual(posted_rows(post), [])

    def test_bad_ingest_floor_days_is_config_error(self):
        cases = (
            {"ingest_floor_days": 0},
            {"ingest_floor_days": -5},
            {"ingest_floor_days": True},
            {"ingest_floor_days": 10 ** 6},
            {"ingest_floor_days": 3651},
            {"ingest_floor_days": 730.0},
        )
        for params in cases:
            with self.subTest(params=params):
                result, session, sleep, post, cooldown = run_cycle_with([], params=params)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["message"], "config:ingest_floor_days")
                self.assertEqual(session.calls, [])
                self.assertEqual(post.calls, [])
                self.assertEqual(cooldown.active_calls, [])

    def test_upper_bound_ingest_floor_days_is_accepted(self):
        result, session, sleep, post, cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, params={"ingest_floor_days": 3650},
        )
        self.assertEqual(result["status"], "ok")
        self.assertIn("date_floor=0", result["message"])

    def test_floored_name_only_item_not_counted_as_isin_conflict(self):
        # Floored items are removed before count_isin_conflicts runs (it takes `recent`), so the
        # old disagreeing name-only item counts only as date_floor. The recent one counts as isin_conflict.
        old = dict(make_item("X", self.CUTOFF - timedelta(days=1), "a"), symbol=None, company="Reliance Limited", isin="INE999Z01099")
        recent = dict(make_item("X", PUB_EARLY, "b"), symbol=None, company="Reliance Limited", isin="INE999Z01099")
        parsed = ParseResult(items=[old, recent], dropped=0)
        by_name = {"RELIANCE LTD": ("RELIANCE", UNIVERSE["RELIANCE"])}
        result, _session, _sleep, post, _cooldown = run_cycle_with(
            [xml_ok()], feeds=ONE_FEED, parse_fn=ParseStub(result=parsed), by_name=by_name,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(posted_rows(post), [])
        self.assertIn("isin_conflict=1 date_floor=1", result["message"])


class AllEightFeedsTests(unittest.TestCase):
    """Every FEEDS entry runs in one cycle, with the real registry, parser and fixture bytes."""

    @staticmethod
    def _responses_in_visit_order(feeds):
        # Responses are consumed in request order, so build them in the rotation order run_cycle uses.
        from pathlib import Path

        fixtures_dir = Path(__file__).resolve().parent / "fixtures" / "home_events"
        responses = []
        for feed in home_events._rotation(feeds, NOW):
            body = (fixtures_dir / f"{feed.feed_code.replace(':', '_')}.xml").read_bytes()
            responses.append(FakeResponse(200, {"Content-Type": "application/xml"}, body))
        return responses

    def test_all_eight_feeds_requested_with_real_registry(self):
        self.assertEqual(len(home_events.FEEDS), 8)
        script = self._responses_in_visit_order(home_events.FEEDS)
        result, session, sleep, post, cooldown = run_cycle_with(
            script, feeds=home_events.FEEDS, parse_fn=home_events.parse,
        )
        url_to_code = {feed.url: feed.feed_code for feed in home_events.FEEDS}
        self.assertEqual(len(session.calls), 8)
        requested_codes = {url_to_code[url] for url in session.calls}
        self.assertEqual(len(requested_codes), 8)
        self.assertEqual(requested_codes, {feed.feed_code for feed in home_events.FEEDS})
        self.assertEqual(cooldown.blocks, [])
        # Fixture items carry symbols outside the two-symbol test universe, so they are rejected as universe.
        self.assertIn("universe", result["message"])
        self.assertEqual(result["status"], "ok")

    def test_nth_feed_403_blocks_once_and_stops(self):
        feeds = home_events.FEEDS
        visit = home_events._rotation(feeds, NOW)
        script = self._responses_in_visit_order(feeds)[:3] + [FakeResponse(403, {}, b"forbidden")]
        result, session, sleep, post, cooldown = run_cycle_with(
            script, feeds=feeds, parse_fn=home_events.parse,
        )
        fourth = visit[3].feed_code
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["message"], f"blocked:{fourth}")
        self.assertEqual(len(cooldown.blocks), 1)
        self.assertEqual(cooldown.blocks[0][2], f"blocked:{fourth}")
        self.assertEqual(cooldown.resets, [])
        self.assertEqual(len(session.calls), 4)  # no request after the 403
        self.assertEqual(session.calls[3], visit[3].url)


if __name__ == "__main__":
    unittest.main()
