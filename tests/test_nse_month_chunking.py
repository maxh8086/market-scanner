"""Month-chunked NSE fetching in scanner/marketdata/factors_postgres.py, offline.

Nothing reaches NSE or Postgres: the session, the database connection, the
coverage writer and time.sleep are all replaced.
"""
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from scanner.marketdata import factors_postgres as fp


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Session:
    """Returns the queued result for each call; an Exception result is raised."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return _Resp(result)


def _run(gaps, session, save_fn=None, cached_fn=None):
    save_fn = save_fn or mock.Mock()
    cached_fn = cached_fn or mock.Mock(return_value=[])
    with mock.patch.object(fp.time, "sleep"), \
            mock.patch.object(fp, "connect"), \
            mock.patch.object(fp, "record_coverage") as coverage:
        rows = fp._fetch_nse_feed(
            feed="announcements", gaps=gaps,
            url="https://example.invalid/api", save_fn=save_fn,
            cached_fn=cached_fn, session=session, label="announcement",
        )
    return rows, save_fn, cached_fn, coverage


class MonthWindowsTest(unittest.TestCase):
    def test_splits_on_calendar_months(self):
        self.assertEqual(
            fp._month_windows(date(2026, 1, 15), date(2026, 3, 10)),
            [(date(2026, 1, 15), date(2026, 1, 31)),
             (date(2026, 2, 1), date(2026, 2, 28)),
             (date(2026, 3, 1), date(2026, 3, 10))],
        )

    def test_single_day(self):
        self.assertEqual(fp._month_windows(date(2026, 5, 5), date(2026, 5, 5)),
                         [(date(2026, 5, 5), date(2026, 5, 5))])

    def test_three_year_window_is_contiguous_and_complete(self):
        start, end = date(2023, 11, 8), date(2026, 11, 8)
        windows = fp._month_windows(start, end)
        self.assertEqual(windows[0][0], start)
        self.assertEqual(windows[-1][1], end)
        for (_, prev_to), (next_from, _) in zip(windows, windows[1:]):
            self.assertEqual((next_from - prev_to).days, 1)
        self.assertEqual(len(windows), 37)


class FetchNseFeedTest(unittest.TestCase):
    def test_each_month_is_fetched_saved_and_recorded(self):
        session = _Session([[{"a": 1}], [{"a": 2}], [{"a": 3}]])
        gap = (date(2026, 1, 1), date(2026, 3, 31))
        rows, save_fn, cached_fn, coverage = _run([gap], session)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(session.calls[0]["from_date"], "01-01-2026")
        self.assertEqual(session.calls[0]["to_date"], "31-01-2026")
        self.assertEqual(rows, [{"a": 1}, {"a": 2}, {"a": 3}])
        self.assertEqual(save_fn.call_count, 3)
        self.assertEqual(coverage.call_count, 3)
        cached_fn.assert_not_called()

    def test_failed_month_falls_back_to_cache_and_window_continues(self):
        # Month 1 fails both attempts; month 2 succeeds on its first attempt.
        session = _Session([RuntimeError("404"), RuntimeError("404"), [{"a": 2}]])
        gap = (date(2026, 1, 1), date(2026, 2, 28))
        cached = [{"cached": True}]
        rows, save_fn, cached_fn, coverage = _run(
            [gap], session, cached_fn=mock.Mock(return_value=cached))
        cached_fn.assert_called_once_with(date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(rows, [{"cached": True}, {"a": 2}])
        # Only the month that saved is recorded as covered.
        self.assertEqual(coverage.call_count, 1)
        self.assertEqual(coverage.call_args.args[2:], (date(2026, 2, 1), date(2026, 2, 28)))

    def test_retry_succeeds_on_second_attempt(self):
        session = _Session([RuntimeError("timeout"), [{"a": 9}]])
        gap = (date(2026, 4, 1), date(2026, 4, 30))
        rows, _, cached_fn, coverage = _run([gap], session)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(rows, [{"a": 9}])
        cached_fn.assert_not_called()
        self.assertEqual(coverage.call_count, 1)

    def test_non_list_payload_is_treated_as_empty_and_still_recorded(self):
        session = _Session([{"error": "no data"}])
        gap = (date(2026, 6, 1), date(2026, 6, 30))
        rows, save_fn, _, coverage = _run([gap], session)
        self.assertEqual(rows, [])
        save_fn.assert_called_once_with([])
        self.assertEqual(coverage.call_count, 1)

    def test_save_failure_is_not_recorded_as_covered(self):
        session = _Session([[{"a": 1}], [{"a": 1}]])
        gap = (date(2026, 7, 1), date(2026, 7, 31))
        save_fn = mock.Mock(side_effect=RuntimeError("db down"))
        cached_fn = mock.Mock(return_value=[])
        _, _, _, coverage = _run([gap], session, save_fn=save_fn, cached_fn=cached_fn)
        coverage.assert_not_called()
        cached_fn.assert_called_once()

    def test_sleep_before_each_attempt_paces_requests(self):
        session = _Session([RuntimeError("x"), []])
        gap = (date(2026, 8, 1), date(2026, 8, 31))
        with mock.patch.object(fp.time, "sleep") as sleep, \
                mock.patch.object(fp, "connect"), \
                mock.patch.object(fp, "record_coverage"):
            fp._fetch_nse_feed(feed="announcements", gaps=[gap],
                               url="u", save_fn=mock.Mock(), cached_fn=mock.Mock(return_value=[]),
                               session=session, label="announcement")
        self.assertEqual([c.args[0] for c in sleep.call_args_list],
                         [fp.REQUEST_INTERVAL_SECONDS, fp.RETRY_BACKOFF_SECONDS])


if __name__ == "__main__":
    unittest.main()
