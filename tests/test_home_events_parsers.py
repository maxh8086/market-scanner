"""Tests for the NSE feed registry and the feed parsers (spec 4.0, 4.3, 6)."""
from __future__ import annotations

import hashlib
import json
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scanner.home_events import FEEDS, PARSERS, ParseError, dedupe_key, parse

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "home_events" / "nse_Financial_Results.xml"
FEED_CODE = "nse:Financial_Results"
FIXTURE_LINK = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"
INTEGRATED_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "home_events" / "nse_Integrated_Filing_Financials.xml"
SAST_REG29_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "home_events" / "nse_Sast_Regulation29.xml"
SAST_REG31_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "home_events" / "nse_Sast_Regulation31.xml"
CORPORATE_ACTION_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "home_events" / "nse_Corporate_action.xml"
CORPORATE_GOVERNANCE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "home_events" / "nse_Corporate_Governance.xml"


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

    def test_fixture_Sast_Regulation29(self):
        body = SAST_REG29_FIXTURE.read_bytes()
        result = parse("nse:Sast_Regulation29", body)
        self.assertEqual(len(result.items), 20)
        self.assertEqual(result.dropped, 0)

        # Literals read from the fixture bytes with xml.etree, not from parse() or the module helpers.
        first = result.items[0]
        self.assertEqual(first["company"], "Jio Financial Services Limited")
        self.assertEqual(
            first["source_url"],
            "https://nsearchives.nseindia.com/corporate/Dis3_11032026125413_54175.zip",
        )
        self.assertEqual(first["published_at"].astimezone(timezone.utc).isoformat(), "2026-11-03T07:24:00+00:00")

        last = result.items[19]
        self.assertEqual(last["company"], "Siddhika Coatings Limited")
        self.assertEqual(
            last["source_url"],
            "https://nsearchives.nseindia.com/corporate/Disclosure_10282026145826_53988.zip",
        )
        self.assertEqual(last["published_at"].astimezone(timezone.utc).isoformat(), "2026-10-28T09:28:00+00:00")

        keys = {
            dedupe_key(
                "nse:Sast_Regulation29",
                item["source_id"],
                item["source_url"],
                item["title"],
                item["description"],
                item["published_at"],
            )
            for item in result.items
        }
        # 20 items with three exact duplicate pairs (items 2/3, 6/7, 9/10) give 17 distinct keys (spec 4.0, 4.2).
        self.assertEqual(len(keys), 17)

    def test_fixture_Sast_Regulation31(self):
        body = SAST_REG31_FIXTURE.read_bytes()
        result = parse("nse:Sast_Regulation31", body)
        self.assertEqual(len(result.items), 20)
        self.assertEqual(result.dropped, 0)

        # Literals read from the fixture bytes with xml.etree, not from parse() or the module helpers.
        first = result.items[0]
        self.assertEqual(first["title"], "Billionbrains Garage Ventures Limited")
        self.assertEqual(first["description"], "NAME OF PROMOTER(S) OR PACS WITH HIM : Fortune First Trust")
        self.assertEqual(first["headline"], "NAME OF PROMOTER(S) OR PACS WITH HIM : Fortune First Trust")
        self.assertEqual(first["company"], "Billionbrains Garage Ventures Limited")
        self.assertEqual(
            first["source_url"],
            "https://nsearchives.nseindia.com/corporate/Fortune_10292026111315.zip",
        )
        self.assertEqual(first["published_at"].astimezone(timezone.utc).isoformat(), "2026-10-29T05:43:15+00:00")

        last = result.items[19]
        self.assertEqual(last["company"], "Ajanta Pharma Limited")
        self.assertEqual(
            last["source_url"],
            "https://nsearchives.nseindia.com/corporate/AJANTPHARM_10212026140918.zip",
        )
        self.assertEqual(last["published_at"].astimezone(timezone.utc).isoformat(), "2026-10-21T08:39:18+00:00")

        keys = {
            dedupe_key(
                "nse:Sast_Regulation31",
                item["source_id"],
                item["source_url"],
                item["title"],
                item["description"],
                item["published_at"],
            )
            for item in result.items
        }
        # 20 items with no repeated dedupe key in the fixture bytes (one-off xml.etree run, spec 4.2).
        self.assertEqual(len(keys), 20)

    def test_fixture_Corporate_action(self):
        body = CORPORATE_ACTION_FIXTURE.read_bytes()
        result = parse("nse:Corporate_action", body)
        self.assertEqual(len(result.items), 58)
        self.assertEqual(result.dropped, 0)

        # Literals read from the fixture bytes with xml.etree, not from parse() or the module helpers.
        first = result.items[0]
        self.assertEqual(first["title"], "TRANSWORLD SHIPPING LINES LIMITED - Ex-Date: 13-Nov-2026")
        self.assertEqual(
            first["description"],
            "SERIES:EQ |PURPOSE:INTERIM DIVIDEND - RS 11 PER SHARE |FACE VALUE:10 |RECORD DATE:13-Nov-2026 "
            "|BOOK CLOSURE START DATE:- |BOOK CLOSURE END DATE:-",
        )
        self.assertEqual(
            first["headline"],
            "SERIES:EQ |PURPOSE:INTERIM DIVIDEND - RS 11 PER SHARE |FACE VALUE:10 |RECORD DATE:13-Nov-2026 "
            "|BOOK CLOSURE START DATE:- |BOOK CLOSURE END DATE:-",
        )
        self.assertEqual(first["company"], "TRANSWORLD SHIPPING LINES LIMITED")
        self.assertEqual(
            first["source_url"],
            "https://www.nseindia.com/companies-listing/corporate-filings-actions",
        )
        self.assertEqual(first["published_at"].astimezone(timezone.utc).isoformat(), "2026-11-10T21:41:42+00:00")

        last = result.items[57]
        self.assertEqual(last["company"], "Venus Pipes & Tubes Limited")
        self.assertEqual(
            last["source_url"],
            "https://www.nseindia.com/companies-listing/corporate-filings-actions",
        )
        self.assertEqual(last["published_at"].astimezone(timezone.utc).isoformat(), "2026-11-10T21:41:42+00:00")

        keys = {
            dedupe_key(
                "nse:Corporate_action",
                item["source_id"],
                item["source_url"],
                item["title"],
                item["description"],
                item["published_at"],
            )
            for item in result.items
        }
        # 58 items with no repeated dedupe key in the fixture bytes (one-off xml.etree run, spec 4.2).
        self.assertEqual(len(keys), 58)

    def test_fixture_Corporate_Governance(self):
        body = CORPORATE_GOVERNANCE_FIXTURE.read_bytes()
        # The sample feed has no <item> elements (spec 4.0). Counted from the raw bytes, not from parse().
        self.assertEqual(len(ET.fromstring(body).findall(".//item")), 0)
        # parse() must not raise on this valid rss document.
        result = parse("nse:Corporate_Governance", body)
        self.assertEqual(result.items, [])
        self.assertEqual(result.dropped, 0)

        # Channel literals read from the fixture bytes with xml.etree, not from parse() or the module helpers.
        channel = ET.fromstring(body).find("channel")
        self.assertEqual(channel.find("title").text, "NSE News - Latest CORPORATE GOVERNANCE")
        self.assertEqual(
            channel.find("link").text,
            "https://www.nseindia.com/companies-listing/corporate-filings-governance",
        )

        keys = {
            dedupe_key(
                "nse:Corporate_Governance",
                item["source_id"],
                item["source_url"],
                item["title"],
                item["description"],
                item["published_at"],
            )
            for item in result.items
        }
        # 0 items in the fixture bytes (one-off xml.etree run), so 0 distinct dedupe keys.
        self.assertEqual(len(keys), 0)

    def test_fixture_Related_Party_Trans(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "home_events" / "nse_Related_Party_Trans.xml"
        body = fixture.read_bytes()
        # Raw-bytes checks with xml.etree, not parse(): 20 items, 10 colon-form and 10 dot-form pubDates (spec 4.0).
        raw_items = ET.fromstring(body).find("channel").findall("item")
        self.assertEqual(len(raw_items), 20)
        self.assertEqual(sum("." in item.find("pubDate").text for item in raw_items), 10)
        self.assertEqual(raw_items[0].find("pubDate").text, "11-SEP-2026 17:49:09")
        self.assertEqual(raw_items[10].find("pubDate").text, "24-MAY-2025 22:28.31")

        result = parse("nse:Related_Party_Trans", body)
        self.assertEqual(len(result.items), 20)
        self.assertEqual(result.dropped, 0)

        # items[0] has a colon-form pubDate; items[10] has the dot-form pubDate above.
        first = result.items[0]
        self.assertEqual(first["title"], "Shree Ram Proteins Limited")
        self.assertEqual(first["description"], "PERIOD END DATE : 30-SEP-2024")
        self.assertEqual(first["headline"], "PERIOD END DATE : 30-SEP-2024")
        self.assertEqual(first["company"], "Shree Ram Proteins Limited")
        self.assertEqual(
            first["source_url"],
            "https://nsearchives.nseindia.com/corporate/xbrl/RPT_1723713_11092026054908_WEB.xml",
        )
        self.assertEqual(first["published_at"].astimezone(timezone.utc).isoformat(), "2026-09-11T12:19:09+00:00")

        dotted = result.items[10]
        self.assertEqual(dotted["company"], "Visdem Technosys Limited")
        self.assertEqual(
            dotted["source_url"],
            "https://nsearchives.nseindia.com/corporate/xbrl/RPT_1450472_24052025102831_WEB.xml",
        )
        self.assertEqual(dotted["published_at"].astimezone(timezone.utc).isoformat(), "2025-05-24T16:58:31+00:00")

        keys = {
            dedupe_key(
                "nse:Related_Party_Trans",
                item["source_id"],
                item["source_url"],
                item["title"],
                item["description"],
                item["published_at"],
            )
            for item in result.items
        }
        # 20 distinct keys derived from the fixture bytes with hashlib and json (one-off run, spec 4.2).
        self.assertEqual(len(keys), 20)

    def test_fixture_Shareholding_Pattern(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "home_events" / "nse_Shareholding_Pattern.xml"
        body = fixture.read_bytes()
        # Raw-bytes checks with xml.etree, not parse(): 1 item, pubDate in the NSE format (spec 4.0).
        raw_items = ET.fromstring(body).find("channel").findall("item")
        self.assertEqual(len(raw_items), 1)
        self.assertEqual(raw_items[0].find("pubDate").text, "11-Nov-2026 12:21:07")

        result = parse("nse:Shareholding_Pattern", body)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.dropped, 0)

        # Literals read from the fixture bytes (one-off xml.etree run), not from parse() or the module helpers.
        first = result.items[0]
        description = (
            "AS ON DATE : 29-Oct-2026 | PR_AND_PRGRP: 69.25 | PUBLIC_VAL: 30.75 | EMPTR: 0 "
            "| NDS_REVISED_STATUS: Revised | SUBMISSION_DT: 03-Nov-2026 | REVISION_DT: 10-Nov-2026"
        )
        self.assertEqual(first["title"], "Indian Toners & Developers Limited")
        self.assertEqual(first["company"], "Indian Toners & Developers Limited")
        self.assertEqual(
            first["source_url"],
            "https://nsearchives.nseindia.com/corporate/xbrl/SHP_1755747_10112026095809_WEB.xml",
        )
        self.assertEqual(first["description"], description)
        self.assertEqual(first["headline"], description)
        # 12:21:07 IST is 06:51:07 UTC.
        self.assertEqual(first["published_at"].astimezone(timezone.utc).isoformat(), "2026-11-11T06:51:07+00:00")

        keys = {
            dedupe_key(
                "nse:Shareholding_Pattern",
                item["source_id"],
                item["source_url"],
                item["title"],
                item["description"],
                item["published_at"],
            )
            for item in result.items
        }
        # 1 item in the fixture bytes, so 1 distinct dedupe key.
        self.assertEqual(len(keys), 1)

    def test_fixture_exists_for_every_feed(self):
        # Completeness after the last T7 parser: every FEEDS entry has a fixture file and a parser (spec 8, 9 T7).
        self.assertEqual(len(FEEDS), 8)
        fixtures_dir = Path(__file__).resolve().parent / "fixtures" / "home_events"
        for feed in FEEDS:
            fixture = fixtures_dir / f"{feed.feed_code.replace(':', '_')}.xml"
            self.assertTrue(fixture.is_file(), f"missing fixture for {feed.feed_code}: {fixture}")
            self.assertIn(feed.feed_code, PARSERS)

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
            parse("nse:No_Such_Feed", b"<rss><channel/></rss>")


if __name__ == "__main__":
    unittest.main()
