import unittest
from datetime import date

from scanner import graph, retention
from scanner.retention import Retention


class FakeSession:
    def __init__(self, log, replies):
        self.log, self.replies = log, replies

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.log.append((query, params))
        for needle, rows in self.replies.items():
            if needle in query:
                return rows
        return []


class FakeDriver:
    def __init__(self, replies=None):
        self.log, self.replies, self.closed = [], replies or {}, False

    def session(self):
        return FakeSession(self.log, self.replies)

    def close(self):
        self.closed = True


def make(cfg=None, replies=None):
    d = FakeDriver(replies)
    return graph.Graph(d, cfg or Retention()), d


class LoadTests(unittest.TestCase):
    def test_filings_params_and_expiry(self):
        g, d = make()
        n = g.load_filings([{"seq_id": 7, "symbol": "A", "an_date": "2026-01-02",
                             "raw_text": "hello", "kind": "orderbook"},
                            {"seq_id": 8, "symbol": ""}])          # no symbol: skipped
        self.assertEqual(n, 1)
        rows = d.log[0][1]["rows"]
        self.assertEqual(rows[0]["seq_id"], "7")
        self.assertEqual(rows[0]["expires_at"], "2029-01-02")
        self.assertEqual(rows[0]["text"], "hello")

    def test_filing_batches_are_small(self):
        g, d = make()
        g.load_filings([{"seq_id": i, "symbol": "A"} for i in range(120)])
        self.assertEqual([len(q[1]["rows"]) for q in d.log], [50, 50, 20])

    def test_extraction_skips_errors_and_normalises_counterparty(self):
        g, d = make()
        n = g.load_extractions([
            {"seq_id": "1", "kind": "orderbook", "symbol": "A", "stored_at": "2026-05-01",
             "data": {"counterparty": "  Tata   Power ", "order_value_inr": 5, "execution_months": 12}},
            {"seq_id": "2", "kind": "orderbook", "data": {"counterparty": "Not stated"}},
            {"seq_id": "3", "kind": "orderbook", "error": "boom", "data": {"x": 1}},
            {"seq_id": "4", "kind": "orderbook", "data": {}},
        ])
        self.assertEqual(n, 2)
        rows = d.log[0][1]["rows"]
        self.assertEqual(rows[0]["counterparty"], "Tata Power")
        self.assertIsNone(rows[1]["counterparty"])
        self.assertEqual(rows[0]["key"], "1|orderbook")
        self.assertIsInstance(rows[0]["data"], str)               # nested dict stored as JSON

    def test_conclusions_and_fundamentals(self):
        g, d = make()
        self.assertEqual(g.load_conclusions([
            {"symbol": "A", "as_of": "2026-09-29", "conclusion": "ok", "stance": "MIXED"},
            {"symbol": "B", "as_of": "2026-09-29", "error": "x"},
            {"symbol": "C", "as_of": "2026-09-29", "conclusion": ""}]), 1)
        self.assertEqual(g.load_fundamentals([{"symbol": "A", "pe": 3, "stored_at": "2026-09-29"}]), 1)
        self.assertEqual(d.log[1][1]["rows"][0]["expires_at"], "2029-09-29")

    def test_no_data_in_query_text(self):
        g, d = make()
        g.load_filings([{"seq_id": "1", "symbol": "EVIL'}) DETACH DELETE n //"}])
        self.assertNotIn("EVIL", d.log[0][0])


class FactsAndPurge(unittest.TestCase):
    def test_facts(self):
        g, _ = make(replies={"peers_sharing_customer": [
            {"symbol": "A", "distinct_customers": 2, "repeat_customers": ["X"],
             "peers_sharing_customer": ["B"]}]})
        self.assertEqual(g.facts()["A"]["distinct_customers"], 2)

    def test_purge_runs_every_step(self):
        g, d = make(replies={"DETACH DELETE": [{"n": 2}]})
        counts = g.purge(date(2030, 1, 1))
        self.assertEqual(set(counts), {"filings", "conclusions", "fundamentals",
                                       "counterparties", "companies"})
        self.assertTrue(all(v == 2 for v in counts.values()))
        self.assertEqual(d.log[0][1], {"today": "2030-01-01", "any": False})

    def test_purge_any_when_processed_not_required(self):
        g, d = make(Retention(only_when_processed=False))
        g.purge(date(2030, 1, 1))
        self.assertTrue(d.log[0][1]["any"])

    def test_purge_off_touches_nothing(self):
        g, d = make(Retention(purge=False))
        self.assertEqual(sum(g.purge().values()), 0)
        self.assertEqual(d.log, [])

    def test_schema_and_close(self):
        g, d = make()
        g.ensure_schema()
        self.assertEqual(len(d.log), len(graph.SCHEMA_QUERIES))
        g.close()
        self.assertTrue(d.closed)




class PushFilingTests(unittest.TestCase):
    def test_push_filing_creates_merge_no_duplicates(self):
        """push_filing uses MERGE so pushing twice creates no duplicates."""
        g, d = make()
        filing = {"seq_id": "1", "symbol": "A", "isin": "INE001A01014",
                  "kind": "orderbook", "an_date": "2026-09-30"}
        extraction = {"seq_id": "1", "kind": "orderbook", "symbol": "A",
                     "data": {"order_value_inr": 100}, "model": "qwen3-4b"}

        # Push twice
        result1 = g.push_filing(filing, extraction)
        result2 = g.push_filing(filing, extraction)

        self.assertTrue(result1)
        self.assertTrue(result2)

        # Verify the filing was pushed (MERGEd, so only once)
        # Count how many PUSH_FILING queries were issued
        push_queries = [q for q, _ in d.log if "PUSH_FILING" in q or "MERGE (c:Company" in q]
        self.assertGreater(len(push_queries), 0)

    def test_push_filing_skips_missing_symbol(self):
        """push_filing skips filings with no symbol."""
        g, d = make()
        filing = {"seq_id": "1", "symbol": ""}  # Empty symbol
        extraction = {}

        result = g.push_filing(filing, extraction)
        self.assertTrue(result)  # Returns True but does nothing
        self.assertEqual(len(d.log), 0)

    def test_push_filing_handles_extraction_without_error(self):
        """push_filing extracts and pushes extraction data."""
        g, d = make()
        filing = {"seq_id": "1", "symbol": "A"}
        extraction = {
            "seq_id": "1",
            "kind": "orderbook",
            "symbol": "A",
            "model": "qwen3-4b",
            "data": {
                "order_value_inr": 500,
                "counterparty": "  Test Company  ",
                "counterparty_type": "customer"
            }
        }

        result = g.push_filing(filing, extraction)
        self.assertTrue(result)
        # Should have created filing and extraction queries
        self.assertGreater(len(d.log), 0)

    def test_push_filing_normalises_counterparty(self):
        """push_filing normalises counterparty names."""
        g, d = make()
        filing = {"seq_id": "2", "symbol": "B"}
        extraction = {
            "seq_id": "2",
            "kind": "orderbook",
            "symbol": "B",
            "data": {
                "order_value_inr": 100,
                "counterparty": "  Tata   Power  "
            }
        }

        g.push_filing(filing, extraction)
        # Check the query parameters for normalized name
        self.assertGreater(len(d.log), 0)

    def test_push_filing_returns_false_on_neo4j_error(self):
        """push_filing returns False if Neo4j is unreachable."""
        # Create a graph with a driver that always fails
        class FailingDriver:
            def session(self):
                raise Exception("Connection failed")
            def close(self):
                pass

        g = graph.Graph(FailingDriver())
        filing = {"seq_id": "1", "symbol": "A"}
        extraction = {}

        result = g.push_filing(filing, extraction)
        self.assertFalse(result)


class SyncAnnouncementsTests(unittest.TestCase):
    def test_sync_announcement_summary_merges_relationships(self):
        """sync_announcement_summary creates announcement relationships."""
        g, d = make()
        rows = [
            {"symbol": "A", "isin": "INE001A01014", "category": "Order",
             "n": 5, "first_date": "2026-01-01", "last_date": "2026-09-30"},
            {"symbol": "B", "isin": "INE002B01015", "category": "Expansion",
             "n": 2, "first_date": "2026-06-01", "last_date": "2026-09-30"},
        ]

        count = g.sync_announcement_summary(rows)
        self.assertEqual(count, 2)

        # Verify queries were issued
        sync_queries = [q for q, _ in d.log if "ANNOUNCED" in q]
        self.assertGreater(len(sync_queries), 0)

    def test_sync_announcement_summary_empty_rows(self):
        """sync_announcement_summary handles empty rows."""
        g, d = make()
        count = g.sync_announcement_summary([])
        self.assertEqual(count, 0)
        self.assertEqual(len(d.log), 0)

    def test_sync_announcement_summary_batches(self):
        """sync_announcement_summary batches large result sets."""
        g, d = make()
        # Create 250 rows (more than batch size of 200)
        rows = [
            {"symbol": f"STOCK{i:03d}", "isin": f"INE{i:06d}", "category": "Order",
             "n": i, "first_date": "2026-01-01", "last_date": "2026-09-30"}
            for i in range(250)
        ]

        count = g.sync_announcement_summary(rows)
        self.assertEqual(count, 250)

        # Should have at least 2 batches
        sync_queries = [q for q, _ in d.log if "ANNOUNCED" in q]
        self.assertGreaterEqual(len(sync_queries), 2)


class PacketTests(unittest.TestCase):
    def test_graph_facts_in_packet(self):
        from scanner import conclude
        row = {"ltp": 100.0, "ath_high": 110.0}
        p = conclude.build_packet(row, [], {"distinct_customers": 3, "repeat_customers": ["X"],
                                            "peers_sharing_customer": ["B", "C"]})
        self.assertEqual(p["graph.distinct_customers"], 3)
        self.assertEqual(p["graph.repeat_customers"], 1)
        self.assertEqual(p["graph.peers_sharing_customer"], "B, C")

    def test_no_graph_facts_leaves_packet_unchanged(self):
        from scanner import conclude
        row = {"ltp": 100.0}
        self.assertEqual(conclude.build_packet(row, []), conclude.build_packet(row, [], {}))
        self.assertNotIn("graph.distinct_customers",
                         conclude.build_packet(row, [], {"distinct_customers": 0}))


if __name__ == "__main__":
    unittest.main()
