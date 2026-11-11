"""Tests for the NSE feed registry and the feed parsers (spec 4.0, 4.3, 6)."""
from __future__ import annotations

import hashlib
import json
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scanner.home_events import FEEDS, ParseError, dedupe_key, parse

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "home_events" / "nse_Financial_Results.xml"
FEED_CODE = "nse:Financial_Results"
FIXTURE_LINK = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"
INTEGRATED_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "home_events" / "nse_Integrated_Filing_Financials.xml"


def _squash(text: str) -> str:
    return " ".join(text.split())


def _rss(*items: str) -> bytes:
    return ('<rss version="2.0"><channel>' + "".join(items) + "</channel></rss>").encode("utf-8")


def _item(
    title: str = "Acme Ltd",
    link: str = "https://example.com/a",
    description: str = "Results",
    pub: str = "03-Nov-2026 10:29:23",
) -> str:
    return (
        f"<item><title>{title}</title><link>{link}</link>"
        f"<description>{description}</description><pubDate>{pub}</pubDate></item>"
    )


class HomeEventsParserTest(unittest.TestCase):
    def test_fixture_nse_financial_results(self):
        body = FIXTURE.read_bytes()
        result = parse(FEED_CODE, body)
        self.assertEqual(len(result.items), 3)
        self.assertEqual(result.dropped, 0)

        utc_times = {item["published_at"].astimezone(timezone.utc).isoformat() for item in result.items}
        self.assertEqual(
            utc_times,
            {
                "2026-11-03T04:25:26+00:00",
                "2026-11-03T04:30:35+00:00",
                "2026-11-03T04:59:23+00:00",
            },
        )
        for item in result.items:
            self.assertEqual(item["company"], "Gammon India Limited")
            self.assertEqual(item["source_url"], FIXTURE_LINK)

        keys = [
            dedupe_key(
                FEED_CODE,
                item["source_id"],
                item["source_url"],
                item["title"],
                item["description"],
                item["published_at"],
            )
            for item in result.items
        ]
        self.assertEqual(len(set(keys)), 3)

        # Expected key for item 0 (file order), built from raw ElementTree text
        # without the module's dedupe_key.
        first = ET.fromstring(body).find("channel").findall("item")[0]
        pub = datetime.strptime(first.find("pubDate").text.strip(), "%d-%b-%Y %H:%M:%S")
        pub = pub.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        payload = json.dumps(
            [
                _squash(first.find("link").text),
                _squash(first.find("title").text),
                _squash(first.find("description").text),
                pub.astimezone(timezone.utc).isoformat(),
            ],
            ensure_ascii=False,
        )
        expected = "nse:Financial_Results:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self.assertEqual(keys[0], expected)

    def test_fixture_Integrated_Filing_Financials(self):
        body = INTEGRATED_FIXTURE.read_bytes()
        result = parse("nse:Integrated_Filing_Financials", body)
        self.assertEqual(len(result.items), 20)
        self.assertEqual(result.dropped, 0)

        # Literals read from the fixture bytes with xml.etree, not from parse() or the module helpers.
        first = result.items[0]
        self.assertEqual(first["company"], "Bajaj Hindusthan Sugar Limited")
        self.assertEqual(
            first["source_url"],
            "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1756034_11112026031015_WEB.xml",
        )
        self.assertEqual(first["published_at"].astimezone(timezone.utc).isoformat(), "2026-11-11T09:38:07+00:00")

        last = result.items[19]
        self.assertEqual(last["company"], "Dar Credit & Capital Limited")
        self.assertEqual(
            last["source_url"],
            "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_NONINDAS_1755909_10112026080955_WEB.xml",
        )
        self.assertEqual(last["published_at"].astimezone(timezone.utc).isoformat(), "2026-11-10T14:39:56+00:00")

        keys = {
            dedupe_key(
                "nse:Integrated_Filing_Financials",
                item["source_id"],
                item["source_url"],
                item["title"],
                item["description"],
                item["published_at"],
            )
            for item in result.items
        }
        self.assertEqual(len(keys), 20)

    def test_empty_feed(self):
        result = parse(FEED_CODE, b'<rss version="2.0"><channel></channel></rss>')
        self.assertEqual(result.items, [])
        self.assertEqual(result.dropped, 0)

    def test_malformed_xml_raises(self):
        with self.assertRaises(ParseError):
            parse(FEED_CODE, b"<rss><channel>")

    def test_html_200_raises(self):
        with self.assertRaises(ParseError):
            parse(FEED_CODE, b"<html><body><p>Access denied</p></body></html>")

    def test_missing_field_dropped_and_counted(self):
        no_link = (
            "<item><title>Beta Ltd</title><description>Results</description>"
            "<pubDate>03-Nov-2026 10:29:23</pubDate></item>"
        )
        result = parse(FEED_CODE, _rss(_item(title="Acme Ltd"), no_link))
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.dropped, 1)

    def test_bad_date_dropped_and_counted(self):
        result = parse(FEED_CODE, _rss(_item(), _item(pub="03/11/2026 09:55:26")))
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.dropped, 1)

    def test_headline_capped_and_title_fallback(self):
        result = parse(
            FEED_CODE,
            _rss(
                _item(title="Long Ltd", description="x" * 600),
                _item(title="  Gamma \n  Ltd  ", description=""),
            ),
        )
        self.assertEqual(len(result.items), 2)
        self.assertEqual(len(result.items[0]["headline"]), 500)
        self.assertEqual(result.items[1]["headline"], "Gamma Ltd")

    def test_feeds_registry_has_eight_rows(self):
        self.assertEqual(len(FEEDS), 8)
        self.assertEqual(
            [feed.feed_code for feed in FEEDS],
            [
                "nse:Financial_Results",
                "nse:Integrated_Filing_Financials",
                "nse:Sast_Regulation29",
                "nse:Sast_Regulation31",
                "nse:Corporate_action",
                "nse:Corporate_Governance",
                "nse:Related_Party_Trans",
                "nse:Shareholding_Pattern",
            ],
        )
        for feed in FEEDS:
            name = feed.feed_code.partition(":")[2]
            self.assertRegex(feed.url, r"^https://nsearchives\.nseindia\.com/content/RSS/[A-Za-z0-9_]+\.xml$")
            self.assertEqual(feed.url, f"https://nsearchives.nseindia.com/content/RSS/{name}.xml")
        self.assertEqual(
            {feed.feed_code for feed in FEEDS if feed.flagged},
            {"nse:Related_Party_Trans", "nse:Shareholding_Pattern"},
        )

    def test_unknown_feed_code_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse("nse:Corporate_action", b"<rss><channel/></rss>")


if __name__ == "__main__":
    unittest.main()
