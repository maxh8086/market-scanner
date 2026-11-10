"""Pure tests for scanner/home_events.py (T3a: redact_error; T3b: dedupe_key and the event-row mapper; T3c: filter_items and classify_response) and the NSE session helper.

Nothing reaches NSE or the network: requests.Session.get is replaced.
"""
from __future__ import annotations

import hashlib
import io
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
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


IST = timezone(timedelta(hours=5, minutes=30))
FEED = home_events.Feed(
    feed_code="nse:Financial_Results",
    url="https://example.invalid/feeds/financial-results.xml",
    event_type="results",
    feed_tier="high_priority",
    default_enabled=True,
    flagged=False,
)
SAMPLE_URL = "https://example.invalid/filings/abc"
SAMPLE_PUBLISHED = datetime(2026, 11, 10, 15, 30, tzinfo=IST)


class DedupeKeyTests(unittest.TestCase):
    def test_with_id(self):
        key = home_events.dedupe_key("nse:Financial_Results", "98765", SAMPLE_URL, SAMPLE_PUBLISHED)
        self.assertEqual(key, "nse:Financial_Results:98765")

    def test_fallback_hash(self):
        key = home_events.dedupe_key("nse:Financial_Results", None, SAMPLE_URL, SAMPLE_PUBLISHED)
        utc_iso = SAMPLE_PUBLISHED.astimezone(timezone.utc).isoformat()
        digest = hashlib.sha256(f"{SAMPLE_URL}|{utc_iso}".encode()).hexdigest()
        self.assertEqual(key, f"nse:Financial_Results:{digest}")
        # An empty id counts as no id.
        self.assertEqual(
            home_events.dedupe_key("nse:Financial_Results", "", SAMPLE_URL, SAMPLE_PUBLISHED), key
        )
        # A naive timestamp would be read as machine-local time, so it is refused.
        with self.assertRaises(ValueError):
            home_events.dedupe_key(
                "nse:Financial_Results", None, SAMPLE_URL, datetime(2026, 11, 10, 15, 30)
            )

    def test_stable_across_refetch(self):
        first = home_events.dedupe_key("nse:Financial_Results", None, SAMPLE_URL, SAMPLE_PUBLISHED)
        refetch = home_events.dedupe_key("nse:Financial_Results", None, SAMPLE_URL, SAMPLE_PUBLISHED)
        same_instant_utc = home_events.dedupe_key(
            "nse:Financial_Results", None, SAMPLE_URL, SAMPLE_PUBLISHED.astimezone(timezone.utc)
        )
        self.assertEqual(first, refetch)
        self.assertEqual(first, same_instant_utc)

    def test_different_link_differs(self):
        first = home_events.dedupe_key("nse:Financial_Results", None, SAMPLE_URL, SAMPLE_PUBLISHED)
        other = home_events.dedupe_key(
            "nse:Financial_Results", None, SAMPLE_URL + "-amended", SAMPLE_PUBLISHED
        )
        self.assertNotEqual(first, other)


class EventRowMapperTests(unittest.TestCase):
    ITEM = {
        "source_id": "98765",
        "source_url": SAMPLE_URL,
        "symbol": "EXAMPLE",
        "isin": "INE000000001",
        "company": "Example Ltd",
        "headline": "Board approves quarterly results",
        "published_at": SAMPLE_PUBLISHED,
    }

    def test_event_row_keys(self):
        row = home_events.to_event_row(FEED, self.ITEM)
        self.assertEqual(
            set(row),
            {
                "dedupe_key", "exchange", "feed_code", "source_id", "source_url", "isin",
                "symbol", "company", "event_type", "feed_tier", "headline", "published_at",
            },
        )
        self.assertEqual(row["dedupe_key"], "nse:Financial_Results:98765")
        self.assertEqual(row["event_type"], "results")
        self.assertEqual(row["feed_tier"], "high_priority")
        self.assertEqual(row["published_at"], "2026-11-10T15:30:00+05:30")

    def test_exchange_from_prefix(self):
        self.assertEqual(home_events.to_event_row(FEED, self.ITEM)["exchange"], "NSE")
        bse_feed = replace(FEED, feed_code="bse:Financial_Results")
        with self.assertRaises(ValueError):
            home_events.to_event_row(bse_feed, self.ITEM)


UNIVERSE = {"EXAMPLE": "INE000000001"}
XML_BODY = b'<?xml version="1.0"?><rss><channel><item/></channel></rss>'


def _parsed_item(symbol: str, isin: str | None = None) -> dict:
    return {
        "source_id": "98765",
        "source_url": SAMPLE_URL,
        "symbol": symbol,
        "isin": isin,
        "company": "Example Ltd",
        "headline": "Board approves quarterly results",
        "published_at": SAMPLE_PUBLISHED,
    }


class FilterItemsTests(unittest.TestCase):
    def test_filter_items_not_in_universe(self):
        items = [_parsed_item("EXAMPLE"), _parsed_item("NOTLISTED")]
        kept, counts = home_events.filter_items(items, UNIVERSE)
        self.assertEqual([item["symbol"] for item in kept], ["EXAMPLE"])
        self.assertEqual(counts, {"universe": 1})

    def test_filter_items_isin_filled(self):
        missing = _parsed_item("EXAMPLE", isin=None)
        supplied = _parsed_item("EXAMPLE", isin="INE999999999")
        kept, counts = home_events.filter_items([missing, supplied], UNIVERSE)
        self.assertEqual([item["isin"] for item in kept], ["INE000000001", "INE999999999"])
        self.assertEqual(counts, {"universe": 0})
        # The caller's dict is not changed.
        self.assertIsNone(missing["isin"])


class ClassifyResponseTests(unittest.TestCase):
    def test_classify_response_none_retry(self):
        self.assertEqual(home_events.classify_response(None, "", b""), "retry")

    def test_classify_response_status_403_blocked(self):
        self.assertEqual(home_events.classify_response(403, "application/xml", XML_BODY), "blocked")

    def test_classify_response_status_429_blocked(self):
        self.assertEqual(home_events.classify_response(429, "application/xml", XML_BODY), "blocked")

    def test_classify_response_html_200_blocked(self):
        # By content type, and by body (a doctype or html tag, after leading whitespace).
        self.assertEqual(
            home_events.classify_response(200, "text/html; charset=utf-8", XML_BODY), "blocked"
        )
        self.assertEqual(
            home_events.classify_response(200, "application/xml", b"  <!DOCTYPE html><html></html>"),
            "blocked",
        )
        self.assertEqual(
            home_events.classify_response(200, "application/xml", b"\n<HTML><body/></HTML>"),
            "blocked",
        )

    def test_classify_response_empty_200_fail(self):
        self.assertEqual(home_events.classify_response(200, "application/xml", b""), "fail")
        self.assertEqual(home_events.classify_response(200, "application/xml", b"  \n"), "fail")

    def test_classify_response_xml_200_ok(self):
        self.assertEqual(home_events.classify_response(200, "application/xml", XML_BODY), "ok")

    def test_classify_response_status_500_retry(self):
        for status in (408, 500, 503):
            with self.subTest(status=status):
                self.assertEqual(
                    home_events.classify_response(status, "application/xml", XML_BODY), "retry"
                )

    def test_classify_response_status_404_fail(self):
        self.assertEqual(home_events.classify_response(404, "application/xml", XML_BODY), "fail")

    def test_classify_response_status_302_fail(self):
        self.assertEqual(home_events.classify_response(302, "text/plain", b""), "fail")


if __name__ == "__main__":
    unittest.main()
