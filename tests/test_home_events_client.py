"""Tests for post_events (T6): batching, bearer auth, summed counts, non-200 handling. Offline: no network."""

from __future__ import annotations

import unittest

from scanner import home_events


BASE_URL = "http://api.test"
TOKEN = "tok-SECRET-123"
TIMEOUT_S = 10
BATCH_URL = "http://api.test/internal/events/batch"


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body

    def json(self):
        return self.body


class FakeHttp:
    """Scripted http client. Each post() records the call and returns the next scripted response."""

    def __init__(self, responses):
        self.calls = []
        self._responses = list(responses)

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if not self._responses:
            raise AssertionError("FakeHttp: no scripted response left for POST %s" % url)
        return self._responses.pop(0)


class PostEventsTests(unittest.TestCase):
    def test_batches_of_500(self):
        rows = [{"dedupe_key": "k%d" % i, "headline": "h%d" % i} for i in range(1200)]
        http = FakeHttp([
            FakeResponse(200, {"inserted": 0, "duplicates": 0, "invalid": 0}),
            FakeResponse(200, {"inserted": 0, "duplicates": 0, "invalid": 0}),
            FakeResponse(200, {"inserted": 0, "duplicates": 0, "invalid": 0}),
        ])

        home_events.post_events(rows, base_url=BASE_URL, token=TOKEN, http=http, timeout_s=TIMEOUT_S)

        self.assertEqual(len(http.calls), 3)
        batch_rows = [call["json"]["rows"] for call in http.calls]
        self.assertEqual([len(b) for b in batch_rows], [500, 500, 200])
        flattened = [r for b in batch_rows for r in b]
        self.assertEqual(flattened, rows)
        for call in http.calls:
            self.assertEqual(call["url"], BATCH_URL)
            self.assertEqual(call["timeout"], TIMEOUT_S)

    def test_bearer_header(self):
        rows = [{"dedupe_key": "a", "headline": "A"}, {"dedupe_key": "b", "headline": "B"}]
        http = FakeHttp([FakeResponse(200, {"inserted": 2, "duplicates": 0, "invalid": 0})])

        home_events.post_events(rows, base_url=BASE_URL, token=TOKEN, http=http, timeout_s=TIMEOUT_S)

        self.assertEqual(http.calls[0]["headers"], {"Authorization": "Bearer tok-SECRET-123"})

    def test_summed_counts(self):
        rows = [{"dedupe_key": "k%d" % i, "headline": "h%d" % i} for i in range(1200)]
        http = FakeHttp([
            FakeResponse(200, {"inserted": 2, "duplicates": 1, "invalid": 0}),
            FakeResponse(200, {"inserted": 0, "duplicates": 3, "invalid": 1}),
            FakeResponse(200, {"inserted": 5, "duplicates": 0, "invalid": 0}),
        ])

        result = home_events.post_events(rows, base_url=BASE_URL, token=TOKEN, http=http, timeout_s=TIMEOUT_S)

        self.assertEqual(result, {"inserted": 7, "duplicates": 4, "invalid": 1})

    def test_non_200_raises_without_token(self):
        rows = [{"dedupe_key": "a", "headline": "A"}, {"dedupe_key": "b", "headline": "B"}]
        for status in (401, 403, 413, 500):
            with self.subTest(status=status):
                http = FakeHttp([FakeResponse(status, {"error": "nope"})])
                with self.assertRaises(RuntimeError) as ctx:
                    home_events.post_events(rows, base_url=BASE_URL, token=TOKEN, http=http, timeout_s=TIMEOUT_S)
                self.assertNotIn("tok-SECRET-123", str(ctx.exception))
