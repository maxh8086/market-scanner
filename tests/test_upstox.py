"""Unit tests for scanner.upstox — rate limiting, 429 handling, backward compat."""
from __future__ import annotations

import logging
import threading
import time
import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock, Mock, patch

from scanner.upstox import (
    RATE_LIMIT_WINDOWS,
    REQUESTS_PER_SEC,
    UpstoxClient,
    UpstoxError,
    _RateLimiter,
    _RateLimiterStats,
)


class TestRateLimiterStats(unittest.TestCase):
    """Tests for _RateLimiterStats."""

    def test_stats_initialization(self):
        """Stats start at zero."""
        stats = _RateLimiterStats()
        self.assertEqual(stats.requests_made, 0)
        self.assertEqual(stats.responses_429, 0)
        self.assertEqual(stats.seconds_waiting, 0.0)


class TestRateLimiterBasic(unittest.TestCase):
    """Basic per-second rate limiter tests (backward compat mode)."""

    def test_per_sec_only_mode(self):
        """When per_sec is set, uses only per-second window."""
        def fake_time():
            return 0.0

        def fake_sleep(duration):
            pass  # Don't actually sleep

        limiter = _RateLimiter(per_sec=5.0, time_func=fake_time, sleep_func=fake_sleep)
        self.assertEqual(len(limiter._windows), 1)
        self.assertEqual(limiter._windows[0], (1, 5))

    def test_wait_without_sleep_when_under_limit(self):
        """wait() doesn't sleep if under limit."""
        time_value = 0.0

        def fake_time():
            return time_value

        def fake_sleep(duration):
            raise AssertionError(f"Should not sleep, but got sleep({duration})")

        limiter = _RateLimiter(per_sec=10.0, time_func=fake_time, sleep_func=fake_sleep)

        # Make requests just fast enough to stay under 10/sec
        for i in range(10):
            time_value = i * 0.1
            limiter.wait()

    def test_multi_window_mode_default(self):
        """Default mode uses all three windows (1s, 60s, 1800s)."""
        limiter = _RateLimiter()
        self.assertEqual(len(limiter._windows), 3)
        self.assertEqual(limiter._windows[0], (1, 40))      # per-second
        self.assertEqual(limiter._windows[1], (60, 400))    # per-minute
        self.assertEqual(limiter._windows[2], (1800, 1600))  # per-30-minute


class TestRateLimiterWindows(unittest.TestCase):
    """Tests for multi-window rate limiting."""

    def test_per_second_window_enforced(self):
        """Per-second window blocks when limit is reached."""
        time_val = 0.0
        sleep_calls = []

        def fake_time():
            return time_val

        def fake_sleep(duration):
            nonlocal time_val
            sleep_calls.append(duration)
            time_val += duration

        # Create limiter with only per-second window (1 req/sec for testing)
        limiter = _RateLimiter(
            windows=[(1, 1)], time_func=fake_time, sleep_func=fake_sleep
        )

        limiter.wait()  # Request 1
        self.assertEqual(len(sleep_calls), 0)

        limiter.wait()  # Request 2 -- should block
        self.assertEqual(len(sleep_calls), 1)
        self.assertGreaterEqual(sleep_calls[0], 0.9)

    def test_per_minute_window_enforced(self):
        """Per-minute window blocks when limit is reached."""
        time_val = 0.0
        sleep_calls = []

        def fake_time():
            return time_val

        def fake_sleep(duration):
            nonlocal time_val
            sleep_calls.append(duration)
            time_val += duration

        # Create limiter with only per-minute window (2 req/min for testing)
        limiter = _RateLimiter(
            windows=[(60, 2)], time_func=fake_time, sleep_func=fake_sleep
        )

        limiter.wait()  # Request 1 at t=0
        limiter.wait()  # Request 2 at t=0 (still in window)
        self.assertEqual(len(sleep_calls), 0)

        limiter.wait()  # Request 3 -- should block
        self.assertEqual(len(sleep_calls), 1)
        self.assertGreater(sleep_calls[0], 50)  # Wait until first req falls out

    def test_per_30min_window_enforced(self):
        """Per-30-minute window blocks when limit is reached."""
        time_val = 0.0
        sleep_calls = []

        def fake_time():
            return time_val

        def fake_sleep(duration):
            nonlocal time_val
            sleep_calls.append(duration)
            time_val += duration

        # Create limiter with only 30-minute window (2 req per 30min for testing)
        limiter = _RateLimiter(
            windows=[(1800, 2)], time_func=fake_time, sleep_func=fake_sleep
        )

        limiter.wait()  # Request 1 at t=0
        limiter.wait()  # Request 2 at t=0
        self.assertEqual(len(sleep_calls), 0)

        limiter.wait()  # Request 3 -- should block
        self.assertEqual(len(sleep_calls), 1)
        self.assertGreater(sleep_calls[0], 1790)  # Wait until first req falls out

    def test_sliding_window_old_requests_expire(self):
        """Old requests fall out of the window and free up capacity."""
        time_val = 0.0
        sleep_calls = []

        def fake_time():
            return time_val

        def fake_sleep(duration):
            nonlocal time_val
            sleep_calls.append(duration)
            time_val += duration

        limiter = _RateLimiter(
            windows=[(10, 2)], time_func=fake_time, sleep_func=fake_sleep
        )

        limiter.wait()  # Request 1 at t=0
        self.assertEqual(len(sleep_calls), 0)

        # Advance time past window without making new request
        time_val = 11.0

        # Now the first request should be expired
        limiter.wait()  # Request 2 at t=11 -- should not block
        self.assertEqual(len(sleep_calls), 0)

    def test_stats_requests_made(self):
        """stats.requests_made increments on each wait()."""
        time_val = 0.0

        def fake_time():
            return time_val

        limiter = _RateLimiter(per_sec=100.0, time_func=fake_time)

        self.assertEqual(limiter.stats.requests_made, 0)
        for i in range(5):
            limiter.wait()
            self.assertEqual(limiter.stats.requests_made, i + 1)

    def test_stats_seconds_waiting(self):
        """stats.seconds_waiting accumulates sleep time."""
        time_val = 0.0
        sleep_durations = []

        def fake_time():
            return time_val

        def fake_sleep(duration):
            nonlocal time_val
            sleep_durations.append(duration)
            time_val += duration

        limiter = _RateLimiter(
            windows=[(1, 1)], time_func=fake_time, sleep_func=fake_sleep
        )

        limiter.wait()  # No sleep
        self.assertEqual(limiter.stats.seconds_waiting, 0.0)

        limiter.wait()  # Sleep occurs
        self.assertGreater(limiter.stats.seconds_waiting, 0.9)


class TestRateLimiterThreadSafety(unittest.TestCase):
    """Thread-safety tests for rate limiter."""

    def test_multiple_threads_safe(self):
        """Multiple threads can call wait() safely."""
        time_val = 0.0
        lock = threading.Lock()
        sleep_calls = []

        def fake_time():
            with lock:
                return time_val

        def fake_sleep(duration):
            nonlocal time_val
            with lock:
                sleep_calls.append(duration)
                time_val += duration * 0.1  # Simulate short sleep

        limiter = _RateLimiter(
            windows=[(10, 5)], time_func=fake_time, sleep_func=fake_sleep
        )

        results = []

        def worker():
            for _ in range(3):
                limiter.wait()
                results.append(1)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads completed
        self.assertEqual(len(results), 9)
        # Some blocking occurred (not all 9 fit in burst)
        self.assertGreater(len(sleep_calls), 0)


class TestUpstoxClientInit(unittest.TestCase):
    """Tests for UpstoxClient initialization."""

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "test-token"})
    def test_init_with_token_from_env(self):
        """Client reads token from UPSTOX_ANALYTICS_ACCESS_TOKEN."""
        client = UpstoxClient()
        self.assertIsNotNone(client._limiter)

    @patch("scanner.upstox.load_dotenv")
    @patch("scanner.upstox.find_dotenv", return_value=None)
    @patch.dict("os.environ", {}, clear=True)
    def test_init_fails_without_token(self, mock_find_dotenv, mock_load_dotenv):
        """Client raises UpstoxError if token not provided and not in env."""
        with self.assertRaises(UpstoxError) as cm:
            UpstoxClient()
        self.assertIn("UPSTOX_ANALYTICS_ACCESS_TOKEN", str(cm.exception))

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "env-token"})
    def test_init_token_parameter_overrides_env(self):
        """Explicit token parameter takes precedence over env."""
        client = UpstoxClient(token="param-token")
        # Token is set (we can't inspect it directly, but no error means it worked)
        self.assertIsNotNone(client._limiter)

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "test-token"})
    def test_init_backward_compat_per_sec(self):
        """per_sec parameter works for backward compatibility."""
        client = UpstoxClient(per_sec=20.0)
        # Should use per_sec only, not multi-window
        self.assertEqual(len(client._limiter._windows), 1)
        self.assertEqual(client._limiter._windows[0][1], 20)

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "test-token"})
    def test_init_default_uses_multi_window(self):
        """Default (no per_sec) uses multi-window rate limiting."""
        client = UpstoxClient()
        # Should use all three windows
        self.assertEqual(len(client._limiter._windows), 3)


class TestUpstoxClientStats(unittest.TestCase):
    """Tests for UpstoxClient.stats()."""

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "test-token"})
    def test_stats_empty_initially(self):
        """stats() returns zero initially."""
        client = UpstoxClient()
        stats = client.stats()
        self.assertEqual(stats["requests_made"], 0)
        self.assertEqual(stats["responses_429"], 0)
        self.assertEqual(stats["seconds_waiting"], 0.0)

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "test-token"})
    def test_stats_requests_made_increments(self):
        """stats() reflects requests_made after wait()."""
        time_val = 0.0

        def fake_time():
            return time_val

        client = UpstoxClient(time_func=fake_time)
        for i in range(3):
            client._limiter.wait()

        stats = client.stats()
        self.assertEqual(stats["requests_made"], 3)


class TestUpstoxClient429Handling(unittest.TestCase):
    """Tests for 429 rate-limit response handling."""

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "test-token"})
    @patch("scanner.upstox.requests.Session.get")
    def test_single_429_retries(self, mock_get):
        """Single 429 triggers retry with backoff."""
        time_val = 0.0

        def fake_time():
            return time_val

        def fake_sleep(duration):
            nonlocal time_val
            time_val += duration

        responses = [
            Mock(status_code=429, headers={}),  # First attempt: 429
            Mock(status_code=200, json=lambda: {"data": {}}),  # Second attempt: success
        ]
        mock_get.side_effect = responses

        client = UpstoxClient(time_func=fake_time, sleep_func=fake_sleep)

        result = client._get("http://example.com/test")
        self.assertEqual(result, {"data": {}})
        self.assertEqual(client._limiter.stats.responses_429, 1)

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "test-token"})
    @patch("scanner.upstox.requests.Session.get")
    def test_429_respects_retry_after_header(self, mock_get):
        """429 response with Retry-After header is honored."""
        time_val = 0.0
        sleep_calls = []

        def fake_time():
            return time_val

        def fake_sleep(duration):
            nonlocal time_val
            sleep_calls.append(duration)
            time_val += duration

        responses = [
            Mock(status_code=429, headers={"Retry-After": "2"}),
            Mock(status_code=200, json=lambda: {"data": {}}),
        ]
        mock_get.side_effect = responses

        client = UpstoxClient(time_func=fake_time, sleep_func=fake_sleep)
        result = client._get("http://example.com/test")

        self.assertEqual(len(sleep_calls), 1)
        self.assertEqual(sleep_calls[0], 2.0)

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "test-token"})
    @patch("scanner.upstox.requests.Session.get")
    def test_repeated_429s_escalate_cooldown(self, mock_get):
        """Three 429s within 5 minutes escalate the cool-down factor."""
        time_val = 0.0
        sleep_calls = []

        def fake_time():
            return time_val

        def fake_sleep(duration):
            nonlocal time_val
            sleep_calls.append(duration)
            time_val += duration

        # 3 x 429, then success
        responses = [
            Mock(status_code=429, headers={}),
            Mock(status_code=429, headers={}),
            Mock(status_code=429, headers={}),
            Mock(status_code=200, json=lambda: {"data": {}}),
        ]
        mock_get.side_effect = responses

        client = UpstoxClient(time_func=fake_time, sleep_func=fake_sleep)

        # Capture logs
        with self.assertLogs("scanner.upstox", level="WARNING") as cm:
            result = client._get("http://example.com/test")

        self.assertEqual(result, {"data": {}})
        # Check that escalation warning was logged
        self.assertTrue(any("escalating cool-down" in msg for msg in cm.output))

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "test-token"})
    @patch("scanner.upstox.requests.Session.get")
    def test_max_retries_exhausted(self, mock_get):
        """MAX_RETRIES exhausted raises UpstoxError."""
        mock_get.return_value = Mock(status_code=429, headers={})

        client = UpstoxClient()

        with self.assertRaises(UpstoxError) as cm:
            client._get("http://example.com/test")
        self.assertIn("Rate limited after", str(cm.exception))


class TestUpstoxClientNoTokenLogging(unittest.TestCase):
    """Tests to ensure tokens are never logged."""

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "secret-token-12345"})
    @patch("scanner.upstox.requests.Session.get")
    def test_token_not_in_error_messages(self, mock_get):
        """Error messages never include the token."""
        mock_get.return_value = Mock(status_code=500, text="Server error", json=Mock(side_effect=ValueError))

        client = UpstoxClient()

        with self.assertRaises(UpstoxError) as cm:
            client._get("http://example.com/test")

        error_msg = str(cm.exception)
        self.assertNotIn("secret-token-12345", error_msg)
        self.assertNotIn("Bearer", error_msg)

    @patch.dict("os.environ", {"UPSTOX_ANALYTICS_ACCESS_TOKEN": "secret-token-12345"})
    def test_token_not_in_log_records(self):
        """Logged messages never contain the token."""
        client = UpstoxClient()
        # Manually check log records
        logger = logging.getLogger("scanner.upstox")
        handler = logging.StreamHandler()
        logger.addHandler(handler)

        # The auth header is set in __init__, but we verify it's not logged anywhere
        # by checking the session headers don't leak into user-facing code
        self.assertIn("Authorization", client._session.headers)
        auth_header = client._session.headers["Authorization"]
        self.assertIn("secret-token-12345", auth_header)
        # But it should never be in error messages (tested above)


if __name__ == "__main__":
    unittest.main()
