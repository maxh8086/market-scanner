"""collect.split_registered: rows with no collector are skipped, not retried every minute. Offline."""
import unittest

from collect import split_registered


class SplitRegisteredTests(unittest.TestCase):
    def test_registered_sources_pass_through(self):
        pairs = [("candles_eod", "schedule"), ("filings", "manual")]
        runnable, missing = split_registered(pairs, {"candles_eod": object(), "filings": object()})
        self.assertEqual(runnable, pairs)
        self.assertEqual(missing, [])

    def test_unregistered_source_is_dropped_and_named_once(self):
        pairs = [("index_eod", "schedule"), ("candles_eod", "schedule"), ("exchange_results", "schedule")]
        runnable, missing = split_registered(pairs, {"candles_eod": object()})
        self.assertEqual(runnable, [("candles_eod", "schedule")])
        self.assertEqual(missing, ["exchange_results", "index_eod"])

    def test_duplicate_missing_name_is_listed_once(self):
        pairs = [("gov_feeds", "manual"), ("gov_feeds", "schedule")]
        runnable, missing = split_registered(pairs, {})
        self.assertEqual(runnable, [])
        self.assertEqual(missing, ["gov_feeds"])


if __name__ == "__main__":
    unittest.main()
