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
