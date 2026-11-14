"""Watchdog API client: GET /internal/due and POST /internal/due/finish, with a fake opener."""
import io
import json
import socket
import unittest
import urllib.error

from scanner.watchdog import api_client as api

CANARY = "CANARY-TOKEN-DO-NOT-LOG"
BASE = "http://127.0.0.1:8081"


class FakeResponse:
    def __init__(self, status=200, body=b""):
        self.status = status
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Recorder:
    """Fake opener: returns or raises the configured outcome and records each request."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def http_error(code):
    return urllib.error.HTTPError(BASE, code, "x", {}, io.BytesIO(b"{}"))


def due_body(sources):
    return json.dumps({"generated_at": "2026-11-14T10:00:00+05:30", "sources": sources})


def source(name, order, service="collector_svc", reason="slot", request_id=None):
    return {"name": name, "service": service, "reason": reason, "request_id": request_id, "order": order}


class FetchDueTests(unittest.TestCase):
    def test_success_parses_and_sorts_by_order(self):
        body = due_body([
            source("candles_eod", 2, request_id="r-1", reason="request"),
            source("index_eod", 1),
        ])
        rec = Recorder(FakeResponse(200, body))
        result = api.fetch_due(BASE, CANARY, 5, opener=rec)
        self.assertTrue(result.ok)
        self.assertIsNone(result.error)
        self.assertEqual([s.name for s in result.sources], ["index_eod", "candles_eod"])
        self.assertIsNone(result.sources[0].request_id)
        self.assertEqual(result.sources[1].request_id, "r-1")
        self.assertIsInstance(result.sources[0], api.DueSource)

    def test_empty_sources_is_ok(self):
        result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(FakeResponse(200, due_body([]))))
        self.assertTrue(result.ok)
        self.assertEqual(result.sources, [])

    def test_request_shape_and_token_only_in_header(self):
        rec = Recorder(FakeResponse(200, due_body([])))
        api.fetch_due(BASE + "/", CANARY, 7, opener=rec)
        req = rec.requests[0]
        self.assertEqual(req.full_url, BASE + "/internal/due")
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.get_header("Authorization"), f"Bearer {CANARY}")
        self.assertNotIn(CANARY, req.full_url)
        self.assertEqual(rec.timeouts, [7])

    def test_401_is_unauthorized(self):
        result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(http_error(401)))
        self.assertEqual((result.ok, result.error), (False, "unauthorized"))
        self.assertEqual(result.sources, [])

    def test_503_is_postgres_down(self):
        result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(http_error(503)))
        self.assertEqual(result.error, "postgres_down")

    def test_500_is_api_unavailable(self):
        result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(http_error(500)))
        self.assertEqual(result.error, "api_unavailable")

    def test_timeout_is_api_unavailable(self):
        result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(socket.timeout("timed out")))
        self.assertEqual(result.error, "api_unavailable")

    def test_connection_refused_is_api_unavailable(self):
        exc = urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
        result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(exc))
        self.assertEqual(result.error, "api_unavailable")

    def test_dns_failure_is_api_unavailable(self):
        exc = urllib.error.URLError(socket.gaierror("no such host"))
        result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(exc))
        self.assertEqual(result.error, "api_unavailable")

    def test_non_200_success_status_is_api_unavailable(self):
        result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(FakeResponse(204, b"")))
        self.assertEqual(result.error, "api_unavailable")

    def test_invalid_json_is_bad_response(self):
        result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(FakeResponse(200, "{nope")))
        self.assertEqual(result.error, "bad_response")

    def test_shape_violations_are_bad_response(self):
        bad_bodies = [
            json.dumps([]),
            json.dumps({"sources": "x"}),
            json.dumps({"sources": None}),
            json.dumps({"sources": ["str"]}),
            json.dumps({"sources": [{"name": "a", "service": "s", "reason": "r", "request_id": None}]}),
            json.dumps({"sources": [source("a", "1")]}),
            json.dumps({"sources": [source("a", True)]}),
            json.dumps({"sources": [{**source("a", 1), "name": 5}]}),
            json.dumps({"sources": [{**source("a", 1), "service": None}]}),
            json.dumps({"sources": [{**source("a", 1), "reason": 1}]}),
            json.dumps({"sources": [{**source("a", 1), "request_id": 12}]}),
        ]
        for body in bad_bodies:
            with self.subTest(body=body):
                result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(FakeResponse(200, body)))
                self.assertEqual((result.ok, result.error), (False, "bad_response"))

    def test_never_raises_on_unexpected_exception(self):
        result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(RuntimeError("boom")))
        self.assertEqual(result.error, "api_unavailable")

    def test_token_never_in_error_result(self):
        result = api.fetch_due(BASE, CANARY, 5, opener=Recorder(http_error(401)))
        self.assertNotIn(CANARY, repr(result))


class FinishKilledTests(unittest.TestCase):
    def test_success_posts_json_with_bearer_header(self):
        rec = Recorder(FakeResponse(200, json.dumps({"finalised": 1})))
        self.assertTrue(api.finish_killed(BASE, CANARY, "home_filings", 4, opener=rec))
        req = rec.requests[0]
        self.assertEqual(req.full_url, BASE + "/internal/due/finish")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(json.loads(req.data), {"source": "home_filings"})
        self.assertEqual(req.get_header("Authorization"), f"Bearer {CANARY}")
        self.assertNotIn(CANARY, req.full_url)
        self.assertNotIn(CANARY, req.data.decode())
        self.assertEqual(rec.timeouts, [4])

    def test_zero_finalised_is_still_true(self):
        rec = Recorder(FakeResponse(200, json.dumps({"finalised": 0})))
        self.assertTrue(api.finish_killed(BASE, CANARY, "home_filings", 4, opener=rec))

    def test_non_200_is_false(self):
        for code in (401, 400, 404, 500, 503):
            with self.subTest(code=code):
                self.assertFalse(api.finish_killed(BASE, CANARY, "home_filings", 4, opener=Recorder(http_error(code))))

    def test_200_with_non_object_json_is_false(self):
        for body in ("[]", "null", "not json", ""):
            with self.subTest(body=body):
                self.assertFalse(api.finish_killed(BASE, CANARY, "x", 4, opener=Recorder(FakeResponse(200, body))))

    def test_timeout_is_false_and_never_raises(self):
        self.assertFalse(api.finish_killed(BASE, CANARY, "x", 4, opener=Recorder(socket.timeout("t"))))

    def test_bad_source_name_is_not_sent(self):
        rec = Recorder(FakeResponse(200, "{}"))
        for bad in ("", "Home", "a-b", "x y", None, 5):
            with self.subTest(bad=bad):
                self.assertFalse(api.finish_killed(BASE, CANARY, bad, 4, opener=rec))
        self.assertEqual(rec.requests, [])


if __name__ == "__main__":
    unittest.main()
