"""Pure tests for scanner/home_events.py (T3a: redact_error) and the NSE session helper.

Nothing reaches NSE or the network: requests.Session.get is replaced.
"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import requests

from scanner import home_events
from scanner.marketdata import factors_postgres as fp


class RedactErrorTests(unittest.TestCase):
    def test_strips_query_string(self):
        text = "feed failed: https://www.nseindia.com/feeds/x.xml?token=abc123&page=2 timed out"
        out = home_events.redact_error(text)
        self.assertIn("https://www.nseindia.com/feeds/x.xml", out)
        self.assertNotIn("?", out)
        self.assertNotIn("token=abc123", out)
        self.assertNotIn("page=2", out)
        self.assertIn("timed out", out)

    def test_strips_token_like(self):
        token = "Zk9aQ2xMb3JlbV9pcHN1bV9kb2xvcl9zaXRfYW1ldDEyMzQ1Njc4"
        text = f"Authorization: Bearer {token} rejected; api_key={token}"
        out = home_events.redact_error(text)
        self.assertNotIn(token, out)
        self.assertIn("<redacted>", out)
        self.assertIn("rejected", out)


class NseSessionTests(unittest.TestCase):
    def test_warmup_failure_not_fatal(self):
        buf = io.StringIO()
        with mock.patch.object(requests.Session, "get", side_effect=OSError("connection reset")):
            with redirect_stdout(buf):
                session = fp.nse_session()
        self.assertIsInstance(session, requests.Session)
        self.assertIn("warm-up failed", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
