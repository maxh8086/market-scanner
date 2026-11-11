"""Offline tests for scanner/company_reference.py. No DB, no network."""
from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scanner import company_reference as cr

AS_OF = date(2026, 11, 1)
ROOT = Path(__file__).resolve().parents[1]


class _FakeTx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.begun = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.conn.committed = exc_type is None
        return False


class _FakeConn:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.begun = False
        self.committed = False

    def transaction(self):
        return _FakeTx(self)

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))


class NormaliseNameTests(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(cr.normalise_name("Dar Credit & Capital Limited"), "DAR CREDIT AND CAPITAL LTD")
        self.assertEqual(cr.normalise_name("Texmo Pipes and Products Limited"), "TEXMO PIPES AND PRODUCTS LTD")
        self.assertEqual(cr.normalise_name("Gammon India Ltd."), "GAMMON INDIA LTD")
        self.assertEqual(cr.normalise_name("  Foo   (Bar)-Baz  "), "FOO BAR BAZ")

    def test_limited_is_whole_token_only(self):
        self.assertEqual(cr.normalise_name("Unlimited Foods"), "UNLIMITED FOODS")

    def test_tatamotors_and_tata_motors_collide_by_design(self):
        # The "-" becomes a space, so these two spellings share a key. This is the M12 case
        # that the collision count must measure; it is recorded here, not hidden.
        self.assertEqual(cr.normalise_name("TATA-MOTORS"), cr.normalise_name("TATA MOTORS"))

    def test_none_and_empty(self):
        self.assertEqual(cr.normalise_name(None), "")
        self.assertEqual(cr.normalise_name(""), "")


class CsvRowsTests(unittest.TestCase):
    def test_builds_rows_and_skips_blanks(self):
        recs = [
            {"Company Name": "Alpha & Co Limited", "Symbol": " alpha ", "ISIN Code": "ine0001", "Series": "EQ"},
            {"Company Name": "No Symbol Ltd", "Symbol": "", "ISIN Code": "INE0002A01010", "Series": "EQ"},
            {"Company Name": "No ISIN Ltd", "Symbol": "NOISIN", "ISIN Code": "  ", "Series": "EQ"},
        ]
        rows = cr.csv_rows(recs, AS_OF)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r.source, r.symbol, r.isin), ("nse_csv", "ALPHA", "INE0001"))
        self.assertEqual(r.name_key, "ALPHA AND CO LTD")
        self.assertEqual(r.series, "EQ")

    def test_duplicate_symbol_isin_keeps_first(self):
        recs = [
            {"Company Name": "First Ltd", "Symbol": "DUP", "ISIN Code": "INE9", "Series": "EQ"},
            {"Company Name": "Second Ltd", "Symbol": "DUP", "ISIN Code": "INE9", "Series": "BE"},
        ]
        rows = cr.csv_rows(recs, AS_OF)
        self.assertEqual([r.company_name for r in rows], ["First Ltd"])


class MasterRowsTests(unittest.TestCase):
    def _raw(self, entries):
        return gzip.compress(json.dumps(entries).encode("utf-8"))

    def test_keeps_only_nse_eq(self):
        raw = self._raw([
            {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "BETA",
             "isin": "INE7", "name": "BETA INDUSTRIES LIMITED"},
            {"segment": "NSE_EQ", "instrument_type": "INDEX", "trading_symbol": "NIFTY",
             "isin": "", "name": "NIFTY 50"},
            {"segment": "BSE_EQ", "instrument_type": "EQ", "trading_symbol": "BETA",
             "isin": "INE7", "name": "BETA INDUSTRIES LIMITED"},
        ])
        rows = cr.master_rows(raw, AS_OF)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].source, rows[0].symbol, rows[0].isin), ("upstox_master", "BETA", "INE7"))
        self.assertEqual(rows[0].name_key, "BETA INDUSTRIES LTD")

    def test_real_master_file_parses_when_present(self):
        path = ROOT / "data" / "upstox_nse_master.json.gz"
        if not path.exists():
            self.skipTest("no local master file")
        rows = cr.master_rows(path.read_bytes(), AS_OF)
        self.assertGreater(len(rows), 2000)


class _ExecConn:
    """Fake psycopg3-style connection: execute() returns an object with fetchall()."""

    def __init__(self, rows):
        self.rows = rows
        self.sql = None

    def execute(self, sql, params=()):
        self.sql = sql
        rows = self.rows
        return type("Cur", (), {"fetchall": lambda _s: rows})()


class _ParamExecConn:
    """Fake psycopg3-style connection that records the SQL and params of execute()."""

    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params=()):
        self.sql = sql
        self.params = tuple(params)
        rows = self.rows
        return type("Cur", (), {"fetchall": lambda _s: rows})()


class IndexTests(unittest.TestCase):
    def test_build_index_union_and_by_name(self):
        idx = cr.build_index([
            ("nse_csv", "ALPHA", "INE1", "ALPHA LTD"),
            ("upstox_master", "ALPHA", "INE1", "ALPHA LTD"),
            ("upstox_master", "BETA", "INE2", "BETA LTD"),
        ])
        self.assertEqual(idx.universe, {"ALPHA": "INE1", "BETA": "INE2"})
        self.assertEqual(idx.by_name, {"ALPHA LTD": ("ALPHA", "INE1"), "BETA LTD": ("BETA", "INE2")})
        self.assertEqual(idx.conflicts, ())

    def test_symbol_with_two_isins_is_excluded(self):
        idx = cr.build_index([
            ("nse_csv", "ALPHA", "INE1", "ALPHA LTD"),
            ("upstox_master", "ALPHA", "INE9", "ALPHA LTD"),
        ])
        self.assertNotIn("ALPHA", idx.universe)
        self.assertNotIn("ALPHA LTD", idx.by_name)
        self.assertIn("symbol:ALPHA", idx.conflicts)

    def test_isin_with_two_symbols_is_excluded(self):
        idx = cr.build_index([
            ("nse_csv", "ALPHA", "INE1", "ALPHA LTD"),
            ("upstox_master", "ALPHX", "INE1", "ALPHX LTD"),
        ])
        self.assertEqual(idx.universe, {})
        self.assertIn("isin:INE1", idx.conflicts)

    def test_name_with_two_pairs_is_ambiguous(self):
        idx = cr.build_index([
            ("nse_csv", "AAA", "INE1", "SAME NAME LTD"),
            ("nse_csv", "BBB", "INE2", "SAME NAME LTD"),
        ])
        self.assertNotIn("SAME NAME LTD", idx.by_name)
        self.assertIn("name:SAME NAME LTD", idx.conflicts)

    def test_fill_from_name_resolves_and_rejects(self):
        by_name = {"ALPHA LTD": ("ALPHA", "INE1")}
        items = [
            {"symbol": None, "isin": None, "company": "Alpha Limited"},
            {"symbol": None, "isin": "INE9", "company": "Alpha Limited"},
            {"symbol": None, "isin": None, "company": "Unknown Co"},
            {"symbol": "KEEP", "isin": None, "company": "Whatever"},
        ]
        out = cr.fill_from_name(items, by_name)
        self.assertEqual((out[0]["symbol"], out[0]["isin"]), ("ALPHA", "INE1"))
        self.assertIsNone(out[1]["symbol"])
        self.assertIsNone(out[2]["symbol"])
        self.assertEqual(out[3]["symbol"], "KEEP")
        self.assertIsNone(items[0]["symbol"])  # input not changed

    def test_load_index_reads_company_reference(self):
        conn = _ExecConn([{"source": "nse_csv", "symbol": "ALPHA", "isin": "INE1", "name_key": "ALPHA LTD"}])
        idx = cr.load_index(conn)
        self.assertIn("company_reference", conn.sql)
        self.assertEqual(idx.universe, {"ALPHA": "INE1"})

    def test_load_index_for_source_filters_by_source(self):
        conn = _ParamExecConn([])
        cr.load_index_for_source(conn, "nse_csv")
        self.assertIn("WHERE source = %s", conn.sql)
        self.assertEqual(conn.params, ("nse_csv",))

    def test_load_index_for_source_builds_from_that_source(self):
        conn = _ParamExecConn([
            {"source": "nse_csv", "symbol": "ALPHA", "isin": "INE1", "name_key": "ALPHA LTD"},
            {"source": "nse_csv", "symbol": "BETA", "isin": "INE2", "name_key": "BETA LTD"},
        ])
        idx = cr.load_index_for_source(conn, "nse_csv")
        self.assertEqual(conn.params, ("nse_csv",))
        self.assertEqual(idx.universe, {"ALPHA": "INE1", "BETA": "INE2"})
        self.assertEqual(idx.by_name, {"ALPHA LTD": ("ALPHA", "INE1"), "BETA LTD": ("BETA", "INE2")})

    def test_load_index_for_source_same_name_two_pairs_is_conflict(self):
        conn = _ParamExecConn([
            {"source": "nse_csv", "symbol": "AAA", "isin": "INE1", "name_key": "SAME NAME LTD"},
            {"source": "nse_csv", "symbol": "BBB", "isin": "INE2", "name_key": "SAME NAME LTD"},
        ])
        idx = cr.load_index_for_source(conn, "nse_csv")
        self.assertNotIn("SAME NAME LTD", idx.by_name)
        self.assertIn("name:SAME NAME LTD", idx.conflicts)


class RefreshTests(unittest.TestCase):
    def _rows(self):
        csv = cr.csv_rows([{"Company Name": "Alpha Ltd", "Symbol": "ALPHA", "ISIN Code": "INE1", "Series": "EQ"}], AS_OF)
        master = cr.master_rows(gzip.compress(json.dumps([
            {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "ALPHA",
             "isin": "INE1", "name": "ALPHA LIMITED"}]).encode()), AS_OF)
        return {"nse_csv": csv, "upstox_master": master}

    def test_replaces_both_sources_in_one_transaction(self):
        conn = _FakeConn()
        counts = cr.refresh(conn, self._rows())
        self.assertEqual(counts, {"nse_csv": 1, "upstox_master": 1})
        self.assertTrue(conn.begun)
        self.assertTrue(conn.committed)
        deletes = [c for c in conn.calls if c[0].startswith("DELETE")]
        self.assertEqual([c[1] for c in deletes], [("nse_csv",), ("upstox_master",)])
        inserts = [c for c in conn.calls if c[0].startswith("INSERT")]
        self.assertEqual(len(inserts), 2)

    def test_empty_source_refuses_and_writes_nothing(self):
        conn = _FakeConn()
        rows = self._rows()
        rows["nse_csv"] = []
        with self.assertRaises(cr.EmptySourceError):
            cr.refresh(conn, rows)
        self.assertEqual(conn.calls, [])
        self.assertFalse(conn.begun)

    def test_missing_source_refuses(self):
        conn = _FakeConn()
        rows = self._rows()
        del rows["upstox_master"]
        with self.assertRaises(cr.EmptySourceError):
            cr.refresh(conn, rows)
        self.assertEqual(conn.calls, [])


class EquityListRowsTests(unittest.TestCase):
    def test_stray_spaces_in_header(self):
        recs = [
            {"SYMBOL": "beta", "NAME OF COMPANY": "Beta Limited", " SERIES": "BE", "ISIN NUMBER": "INE2"},
            {"SYMBOL": "NOISIN", "NAME OF COMPANY": "No ISIN Ltd", " SERIES": "EQ", "ISIN NUMBER": "  "},
        ]
        rows = cr.equity_list_rows(recs, AS_OF)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r.source, "nse_csv")
        self.assertEqual(r.symbol, "BETA")
        self.assertEqual(r.series, "BE")


class JobTests(unittest.TestCase):
    def test_run_refresh_uses_fetched_sources(self):
        from scanner import company_reference_job as job

        csv_raw = ("SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
                   "ALPHA,Alpha Limited, EQ,06-OCT-2008,5,1,INE1,5\n").encode("utf-8-sig")
        master_raw = gzip.compress(json.dumps([
            {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "BETA",
             "isin": "INE2", "name": "BETA LIMITED"}]).encode())
        conn = _FakeConn()
        counts = job.run_refresh(conn, today=AS_OF,
                                 fetch_csv=lambda: csv_raw, fetch_master=lambda: master_raw,
                                 fetch_indexes=lambda: {"NIFTY TOTAL MARKET": INDEX_RAW})
        self.assertEqual(counts, {"nse_csv": 1, "upstox_master": 1, "NIFTY TOTAL MARKET": 1})
        self.assertTrue(conn.committed)

    def test_run_refresh_fetch_failure_writes_nothing(self):
        from scanner import company_reference_job as job

        def boom():
            raise RuntimeError("network down")

        conn = _FakeConn()
        with self.assertRaises(RuntimeError):
            job.run_refresh(conn, today=AS_OF, fetch_csv=boom,
                            fetch_master=lambda: gzip.compress(b"[]"),
                            fetch_indexes=lambda: {"NIFTY TOTAL MARKET": INDEX_RAW})
        self.assertEqual(conn.calls, [])


INDEX_RAW = (
    "Company Name,Industry,Symbol,Series,ISIN Code\n"
    "Alpha Ltd,IT,ALPHA,EQ,INE1\n"
    "DUMMY ROW,NA,DUMMYX,EQ,INE9\n"
).encode("utf-8-sig")


class ConstituentRowsTests(unittest.TestCase):
    def test_dummy_blank_and_index_name(self):
        recs = [
            {"Company Name": " Alpha Ltd ", "Industry": " IT ", "Symbol": " alpha ", "Series": "EQ", "ISIN Code": "ine1"},
            {"Company Name": "Dummy", "Industry": "NA", "Symbol": "DUMMYX", "Series": "EQ", "ISIN Code": "INE9"},
            {"Company Name": "No Symbol", "Industry": "IT", "Symbol": "  ", "Series": "EQ", "ISIN Code": "INE2"},
            {"Company Name": "No ISIN", "Industry": "IT", "Symbol": "NOISIN", "Series": "EQ", "ISIN Code": ""},
        ]
        rows = cr.constituent_rows(recs, AS_OF, "NIFTY TOTAL MARKET")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {
            "index_name": "NIFTY TOTAL MARKET", "symbol": "ALPHA", "isin": "INE1",
            "company_name": "Alpha Ltd", "industry": "IT", "series": "EQ",
        })

    def test_duplicate_symbol_isin_kept_once(self):
        recs = [
            {"Company Name": "First", "Industry": "IT", "Symbol": "DUP", "Series": "EQ", "ISIN Code": "INE5"},
            {"Company Name": "Second", "Industry": "IT", "Symbol": "DUP", "Series": "BE", "ISIN Code": "INE5"},
        ]
        rows = cr.constituent_rows(recs, AS_OF, "X")
        self.assertEqual([r["company_name"] for r in rows], ["First"])


class ReplaceIndexTests(unittest.TestCase):
    ROWS = [
        {"index_name": "NIFTY TOTAL MARKET", "symbol": "ALPHA", "isin": "INE1",
         "company_name": "Alpha Ltd", "industry": "IT", "series": "EQ"},
        {"index_name": "NIFTY TOTAL MARKET", "symbol": "BETA", "isin": "INE2",
         "company_name": "Beta Ltd", "industry": None, "series": None},
    ]

    def test_deletes_only_this_index_and_inserts_in_one_transaction(self):
        conn = _FakeConn()
        n = cr.replace_index_constituents(conn, "NIFTY TOTAL MARKET", self.ROWS, AS_OF)
        self.assertEqual(n, 2)
        self.assertTrue(conn.begun)
        self.assertTrue(conn.committed)
        deletes = [c for c in conn.calls if c[0].startswith("DELETE")]
        self.assertEqual(deletes, [("DELETE FROM index_constituents WHERE index_name = %s", ("NIFTY TOTAL MARKET",))])
        inserts = [c for c in conn.calls if c[0].startswith("INSERT INTO index_constituents")]
        self.assertEqual(len(inserts), 2)
        self.assertEqual(inserts[0][1], ("NIFTY TOTAL MARKET", "ALPHA", "INE1", "Alpha Ltd", "IT", "EQ", AS_OF))

    def test_empty_list_refuses_and_writes_nothing(self):
        conn = _FakeConn()
        with self.assertRaises(cr.EmptySourceError):
            cr.replace_index_constituents(conn, "NIFTY TOTAL MARKET", [], AS_OF)
        self.assertEqual(conn.calls, [])
        self.assertFalse(conn.begun)


class LoadIndexConstituentsTests(unittest.TestCase):
    def test_returns_csv_style_keys(self):
        conn = _ExecConn([{"symbol": "ALPHA", "isin": "INE1", "company_name": "Alpha Ltd",
                           "industry": "IT", "series": "EQ"}])
        out = cr.load_index_constituents(conn, "NIFTY TOTAL MARKET")
        self.assertIn("index_constituents", conn.sql)
        self.assertEqual(out, [{"Symbol": "ALPHA", "ISIN Code": "INE1", "Company Name": "Alpha Ltd",
                                "Industry": "IT", "Series": "EQ"}])

    def test_tuple_rows_accepted(self):
        out = cr.load_index_constituents(_ExecConn([("ALPHA", "INE1", "Alpha Ltd", "IT", "EQ")]), "X")
        self.assertEqual(out[0]["ISIN Code"], "INE1")

    def test_empty_index_raises_naming_it(self):
        with self.assertRaises(RuntimeError) as ctx:
            cr.load_index_constituents(_ExecConn([]), "NIFTY TOTAL MARKET")
        self.assertIn("NIFTY TOTAL MARKET", str(ctx.exception))
        self.assertIn("monthly job", str(ctx.exception))


class LoadMasterFromDbTests(unittest.TestCase):
    def test_shape_and_source_filter(self):
        conn = _ExecConn([{"symbol": "BETA", "isin": "INE2"}, ("GAMMA", "INE3")])
        m = cr.load_master_from_db(conn)
        self.assertIn("source = %s", conn.sql)
        self.assertEqual(m, {"by_symbol": {"BETA": "INE2", "GAMMA": "INE3"},
                             "by_isin": {"INE2": "BETA", "INE3": "GAMMA"}})

    def test_empty_raises(self):
        with self.assertRaises(RuntimeError):
            cr.load_master_from_db(_ExecConn([]))


class IndexJobTests(unittest.TestCase):
    def _run(self, conn, **overrides):
        from scanner import company_reference_job as job

        kwargs = dict(
            today=AS_OF,
            fetch_csv=lambda: ("SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
                               "ALPHA,Alpha Limited, EQ,06-OCT-2008,5,1,INE1,5\n").encode("utf-8-sig"),
            fetch_master=lambda: gzip.compress(json.dumps([
                {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "BETA",
                 "isin": "INE2", "name": "BETA LIMITED"}]).encode()),
            fetch_indexes=lambda: {"NIFTY TOTAL MARKET": INDEX_RAW},
        )
        kwargs.update(overrides)
        return job.run_refresh(conn, **kwargs)

    def test_writes_each_index_after_sources(self):
        conn = _FakeConn()
        counts = self._run(conn)
        self.assertEqual(counts["NIFTY TOTAL MARKET"], 1)
        deletes = [c[1] for c in conn.calls if c[0].startswith("DELETE FROM index_constituents")]
        self.assertEqual(deletes, [("NIFTY TOTAL MARKET",)])
        self.assertTrue(conn.committed)

    def test_failed_index_fetch_writes_nothing(self):
        conn = _FakeConn()

        def boom():
            raise RuntimeError("index 'NIFTY TOTAL MARKET' download failed from every source")

        with self.assertRaises(RuntimeError):
            self._run(conn, fetch_indexes=boom)
        self.assertEqual(conn.calls, [])
        self.assertFalse(conn.begun)

    def test_empty_index_refuses_whole_refresh(self):
        conn = _FakeConn()
        with self.assertRaises(cr.EmptySourceError):
            self._run(conn, fetch_indexes=lambda: {"NIFTY TOTAL MARKET": b"Company Name,Industry,Symbol,Series,ISIN Code\n"})
        self.assertEqual(conn.calls, [])

    def test_index_missing_from_fetch_result_refuses(self):
        conn = _FakeConn()
        with self.assertRaises(RuntimeError):
            self._run(conn, fetch_indexes=lambda: {})
        self.assertEqual(conn.calls, [])


class LoaderDsnTests(unittest.TestCase):
    BASE = {"POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5432", "POSTGRES_DB": "market_scanner"}

    def _pw_file(self, tmp, text):
        p = Path(tmp) / "loader_pw"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_reads_password_from_file(self):
        from scanner import company_reference_job as job

        with tempfile.TemporaryDirectory() as tmp:
            env = dict(self.BASE, POSTGRES_LOADER_PASSWORD_FILE=self._pw_file(tmp, "s3cret-pw\n"))
            dsn = job.loader_dsn(env)
        self.assertIn("password=s3cret-pw", dsn)
        self.assertIn("user=market_scanner_loader", dsn)
        self.assertIn("dbname=market_scanner", dsn)

    def test_password_not_taken_from_env(self):
        from scanner import company_reference_job as job

        with tempfile.TemporaryDirectory() as tmp:
            env = dict(self.BASE, POSTGRES_PASSWORD="wrong",
                       POSTGRES_LOADER_PASSWORD_FILE=self._pw_file(tmp, "s3cret-pw\n"))
            dsn = job.loader_dsn(env)
        self.assertNotIn("wrong", dsn)

    def test_unset_variable_refused(self):
        from scanner import company_reference_job as job

        with self.assertRaises(RuntimeError):
            job.loader_dsn(dict(self.BASE))

    def test_empty_file_refused(self):
        from scanner import company_reference_job as job

        with tempfile.TemporaryDirectory() as tmp:
            env = dict(self.BASE, POSTGRES_LOADER_PASSWORD_FILE=self._pw_file(tmp, "  \n\t\n"))
            with self.assertRaises(RuntimeError):
                job.loader_dsn(env)

    def test_missing_file_refused(self):
        from scanner import company_reference_job as job

        with tempfile.TemporaryDirectory() as tmp:
            env = dict(self.BASE, POSTGRES_LOADER_PASSWORD_FILE=str(Path(tmp) / "does-not-exist"))
            with self.assertRaises(RuntimeError):
                job.loader_dsn(env)

    def test_loader_user_override(self):
        from scanner import company_reference_job as job

        with tempfile.TemporaryDirectory() as tmp:
            env = dict(self.BASE, POSTGRES_LOADER_USER="other_loader",
                       POSTGRES_LOADER_PASSWORD_FILE=self._pw_file(tmp, "s3cret-pw\n"))
            dsn = job.loader_dsn(env)
        self.assertIn("user=other_loader", dsn)


if __name__ == "__main__":
    unittest.main()
