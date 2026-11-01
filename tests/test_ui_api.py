"""Contract tests for the UI API, run read-only against the live Postgres.

They skip when Postgres is unreachable or holds no completed run. The two config
validation tests reject before any write, so they change nothing.

    Load the project's .env first to run them from the host (the Postgres values there point at 127.0.0.1).
"""
import unittest

try:
    from scanner.pg import db as pg_db
    _PG = pg_db.available()
except Exception:
    _PG = False

if _PG:
    from fastapi.testclient import TestClient
    from ui.app.main import app


def _first_run(client):
    runs = client.get("/api/runs").json().get("runs", [])
    return runs[0] if runs else None


@unittest.skipUnless(_PG, "Postgres is not reachable")
class UIApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.latest = _first_run(cls.client)
        if cls.latest is None:
            raise unittest.SkipTest("no completed run in Postgres")

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_runs_carry_counts_from_snapshots(self):
        run = self.latest
        self.assertGreater(run["scanned"], 0)
        self.assertGreaterEqual(run["in_range"], run["at_ath"])
        self.assertEqual(run["in_range"],
                         run["at_ath"] + run["within_5"] + run["within_10"] + run["within_26"])
        self.assertEqual(run["stance_constructive"] + run["stance_mixed"] + run["stance_cautious"],
                         run["scanned"])

    def test_runs_newest_first_and_one_per_date(self):
        runs = self.client.get("/api/runs").json()["runs"]
        dates = [r["run_date"] for r in runs]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(len(dates), len(set(dates)))

    def test_run_detail_matches_list(self):
        detail = self.client.get(f"/api/runs/{self.latest['run_id']}").json()["run"]
        for k in ("run_date", "scanned", "in_range", "at_ath"):
            self.assertEqual(str(detail[k]), str(self.latest[k]))

    def test_results_paginate_and_total_matches_snapshots(self):
        rid = self.latest["run_id"]
        a = self.client.get(f"/api/runs/{rid}/results?page=1&per_page=10").json()
        b = self.client.get(f"/api/runs/{rid}/results?page=2&per_page=10").json()
        self.assertEqual(len(a["results"]), 10)
        self.assertEqual(a["total"], self.latest["scanned"] + self._left_range(rid))
        self.assertTrue({r["symbol"] for r in a["results"]}.isdisjoint(
            {r["symbol"] for r in b["results"]}))

    def _left_range(self, rid):
        data = self.client.get(f"/api/runs/{rid}/results?per_page=100&bucket=left_range").json()
        return data.get("total", 0)

    def test_results_filter_by_bucket(self):
        rid = self.latest["run_id"]
        data = self.client.get(f"/api/runs/{rid}/results?bucket=at_ath&per_page=100").json()
        self.assertEqual(data["total"], self.latest["at_ath"])
        self.assertTrue(all(r["bucket"] == "at_ath" for r in data["results"]))

    def test_stock_dashboard_has_timeline(self):
        rid = self.latest["run_id"]
        symbol = self.client.get(f"/api/runs/{rid}/results?per_page=1").json()["results"][0]["symbol"]
        data = self.client.get(f"/api/stocks/{symbol}").json()
        self.assertEqual(data["snapshot"]["symbol"], symbol)
        self.assertGreaterEqual(len(data["timeline"]), 1)
        dates = [t["run_date"] for t in data["timeline"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_unknown_stock_reports_not_found(self):
        self.assertEqual(self.client.get("/api/stocks/NOSUCHSYMBOL").json()["error"],
                         "Stock not found")

    def test_stocks_list_has_total_and_rows(self):
        data = self.client.get("/api/stocks?limit=5").json()
        self.assertIn("total", data)
        self.assertLessEqual(len(data["rows"]), 5)
        for row in data["rows"]:
            for key in ("symbol", "bucket", "stance_score", "run_date"):
                self.assertIn(key, row)

    def test_stocks_list_one_row_per_symbol(self):
        data = self.client.get("/api/stocks?limit=200").json()
        symbols = [r["symbol"] for r in data["rows"]]
        self.assertEqual(len(symbols), len(set(symbols)))

    def test_stocks_list_search_matches_symbol(self):
        first = self.client.get("/api/stocks?limit=1").json()["rows"]
        if not first:
            self.skipTest("no stocks in Postgres")
        needle = first[0]["symbol"][:2]
        data = self.client.get(f"/api/stocks?q={needle}&limit=200").json()
        self.assertTrue(all(needle in r["symbol"] for r in data["rows"]))

    def test_stocks_list_pages_are_disjoint(self):
        a = self.client.get("/api/stocks?limit=10&offset=0").json()["rows"]
        b = self.client.get("/api/stocks?limit=10&offset=10").json()["rows"]
        self.assertTrue({r["symbol"] for r in a}.isdisjoint({r["symbol"] for r in b}))

    def test_cost_counts_only_real_llm_calls(self):
        """A run with no llm_calls rows must report 0 calls, not 1."""
        rid = self.latest["run_id"]
        m = self.client.get(f"/api/cost/{rid}").json()["metrics"]
        from scanner.pg import db
        with db.connect() as conn:
            n = conn.execute("SELECT COUNT(*) AS n FROM llm_calls WHERE run_id = %s",
                             (rid,)).fetchone()["n"]
        self.assertEqual(m["llm_calls"], n)
        if n == 0:
            self.assertIsNone(m["total_input_tokens"])

    def test_cost_has_no_prices(self):
        body = self.client.get("/api/cost").text.lower()
        for word in ("price", "usd", "dollar", "$"):
            self.assertNotIn(word, body)

    def test_report_matches_runs(self):
        report = self.client.get("/api/report").json()["runs"]
        by_id = {r["run_id"]: r for r in report}
        self.assertIn(self.latest["run_id"], by_id)
        self.assertEqual(by_id[self.latest["run_id"]]["in_range"], self.latest["in_range"])

    def test_config_lists_all_five_sources(self):
        sources = {s["source"] for s in self.client.get("/api/config").json()["sources"]}
        self.assertEqual(sources, {"candles_eod", "announcements", "corporate_actions",
                                   "filings", "fundamentals"})

    def test_responses_do_not_leak_credentials(self):
        for path in ("/api/runs", "/api/config", "/api/cost"):
            body = self.client.get(path).text.lower()
            self.assertNotIn("password", body)
            self.assertNotIn("postgres://", body)
            self.assertNotIn("mongodb://", body)

    def test_invalid_cron_rejected(self):
        r = self.client.put("/api/config/candles_eod", json={"mode": "scheduled", "cron": "invalid cron"})
        self.assertEqual(r.status_code, 400)

    def test_invalid_mode_rejected(self):
        r = self.client.put("/api/config/candles_eod", json={"mode": "invalid", "cron": "0 * * * *"})
        self.assertEqual(r.status_code, 400)

    def test_unknown_source_rejected(self):
        r = self.client.put("/api/config/not_a_source", json={"mode": "manual", "cron": "0 * * * *"})
        self.assertEqual(r.status_code, 400)


class DescribeCronTests(unittest.TestCase):
    @unittest.skipUnless(_PG, "ui.app imports need the DB layer")
    def test_describe(self):
        from ui.app.api import _describe_cron
        self.assertIn("35", _describe_cron("35 18 * * 1-5"))
        self.assertIn("30", _describe_cron("*/30 8-20 * * 1-5"))


if __name__ == "__main__":
    unittest.main()
