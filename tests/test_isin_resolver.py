"""Offline tests for scanner.isin_resolver. No network and no database."""
import unittest
from datetime import date
from unittest import mock

from scanner import isin_resolver as ir

MASTER = {
    "by_symbol": {"CCAVENUE": "INE483S01038", "RELIANCE": "INE002A01018", "NEWNAME": "INEREN0100X"},
    "by_isin": {"INE483S01038": "CCAVENUE", "INE002A01018": "RELIANCE", "INEREN0100X": "NEWNAME"},
}


class FakeConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))


class _MasterCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _MasterConn:
    """Fake connection for the company_reference read: execute() returns rows from fetchall()."""

    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params=()):
        self.sql = " ".join(sql.split())
        self.params = params
        return _MasterCursor(self.rows)


class ResolveTests(unittest.TestCase):
    def test_unchanged_isin(self):
        r = ir.resolve("RELIANCE", "INE002A01018", MASTER)
        self.assertEqual((r.symbol, r.isin), ("RELIANCE", "INE002A01018"))
        self.assertFalse(r.changed)
        self.assertIsNone(r.renamed_from)
        self.assertTrue(r.resolved)

    def test_changed_isin_ccavenue(self):
        r = ir.resolve("CCAVENUE", "INE483S01020", MASTER)
        self.assertEqual(r.isin, "INE483S01038")
        self.assertTrue(r.changed)
        self.assertIsNone(r.renamed_from)
        self.assertIn("INE483S01020", r.reason)

    def test_rename_via_isin(self):
        r = ir.resolve("OLDNAME", "INEREN0100X", MASTER)
        self.assertEqual(r.symbol, "NEWNAME")
        self.assertEqual(r.isin, "INEREN0100X")
        self.assertEqual(r.renamed_from, "OLDNAME")
        self.assertTrue(r.changed)
        self.assertTrue(r.resolved)

    def test_unresolved_keeps_csv_values(self):
        r = ir.resolve("GHOST", "INE000000000", MASTER)
        self.assertEqual((r.symbol, r.isin), ("GHOST", "INE000000000"))
        self.assertFalse(r.changed)
        self.assertFalse(r.resolved)
        self.assertIn("not found in master", r.reason)

    def test_blank_isin_uses_master(self):
        r = ir.resolve("CCAVENUE", "", MASTER)
        self.assertEqual(r.isin, "INE483S01038")
        self.assertTrue(r.resolved)
        r_none = ir.resolve("CCAVENUE", None, MASTER)
        self.assertEqual(r_none.isin, "INE483S01038")

    def test_blank_isin_unknown_symbol_is_unresolved(self):
        r = ir.resolve("GHOST", "  ", MASTER)
        self.assertFalse(r.resolved)
        self.assertEqual(r.isin, "")

    def test_case_insensitive(self):
        r = ir.resolve("ccavenue", "ine483s01020", MASTER)
        self.assertEqual((r.symbol, r.isin), ("CCAVENUE", "INE483S01038"))
        self.assertTrue(r.changed)
        r2 = ir.resolve(" reliance ", "ine002a01018", MASTER)
        self.assertFalse(r2.changed)
        self.assertEqual(r2.symbol, "RELIANCE")


class RecordTests(unittest.TestCase):
    def test_record_upserts_history_and_alias(self):
        results = [
            ir.resolve("CCAVENUE", "INE483S01020", MASTER),
            ir.resolve("OLDNAME", "INEREN0100X", MASTER),
            ir.resolve("GHOST", "INE000000000", MASTER),
        ]
        conn = FakeConn()
        written = ir.record(conn, results, today=date(2026, 11, 2))
        self.assertEqual(written, 3)  # two history rows + one alias row; unresolved skipped
        history = [c for c in conn.calls if c[0].startswith("INSERT INTO isin_history")]
        alias = [c for c in conn.calls if c[0].startswith("INSERT INTO symbol_alias")]
        self.assertEqual(len(history), 2)
        self.assertEqual(len(alias), 1)
        self.assertIn("ON CONFLICT (symbol, isin)", history[0][0])
        self.assertNotIn("first_seen = EXCLUDED", history[0][0])  # first_seen is kept
        self.assertEqual(history[0][1], ("CCAVENUE", "INE483S01038", date(2026, 11, 2), date(2026, 11, 2), ir.SOURCE))
        self.assertIn("ON CONFLICT (old_symbol, new_symbol, isin)", alias[0][0])
        self.assertEqual(alias[0][1], ("OLDNAME", "NEWNAME", "INEREN0100X", date(2026, 11, 2)))

    def test_record_defaults_today(self):
        conn = FakeConn()
        ir.record(conn, [ir.resolve("RELIANCE", "INE002A01018", MASTER)])
        self.assertEqual(conn.calls[0][1][2], date.today())


class ResolveAllTests(unittest.TestCase):
    def test_loads_master_once_and_records_with_conn(self):
        pairs = [("CCAVENUE", "INE483S01020"), ("RELIANCE", "INE002A01018")]
        with mock.patch.object(ir, "load_master", return_value=MASTER) as lm:
            conn = FakeConn()
            out = ir.resolve_all(pairs, conn=conn)
        self.assertEqual(lm.call_count, 1)
        lm.assert_called_once_with(conn)
        self.assertEqual([r.isin for r in out], ["INE483S01038", "INE002A01018"])
        self.assertEqual(len(conn.calls), 2)

    def test_record_results_false_writes_nothing(self):
        statements = []

        class _ReadOnlyConn(_MasterConn):
            def execute(self, sql, params=()):
                statements.append(" ".join(sql.split()))
                return super().execute(sql, params)

        conn = _ReadOnlyConn([
            {"symbol": "CCAVENUE", "isin": "INE483S01038"},
            {"symbol": "RELIANCE", "isin": "INE002A01018"},
        ])
        pairs = [("CCAVENUE", "INE483S01020"), ("RELIANCE", "INE002A01018")]
        out = ir.resolve_all(pairs, conn, record_results=False)
        self.assertEqual(len(statements), 1)  # the master read only
        self.assertIn("company_reference", statements[0])
        self.assertEqual([r.isin for r in out], ["INE483S01038", "INE002A01018"])


class LoadMasterFromDbTests(unittest.TestCase):
    def test_shape_matches_resolver(self):
        conn = _MasterConn([
            {"symbol": "CCAVENUE", "isin": "INE483S01038"},
            {"symbol": "RELIANCE", "isin": "INE002A01018"},
        ])
        m = ir.load_master(conn)
        self.assertEqual(m["by_symbol"], {"CCAVENUE": "INE483S01038", "RELIANCE": "INE002A01018"})
        self.assertEqual(m["by_isin"], {"INE483S01038": "CCAVENUE", "INE002A01018": "RELIANCE"})
        self.assertIn("company_reference", conn.sql)
        self.assertEqual(conn.params, ("upstox_master",))

    def test_tuple_rows_accepted(self):
        m = ir.load_master(_MasterConn([("RELIANCE", "INE002A01018")]))
        self.assertEqual(m["by_isin"], {"INE002A01018": "RELIANCE"})

    def test_no_connection_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            ir.load_master(None)
        self.assertIn("no database connection", str(ctx.exception))

    def test_empty_table_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            ir.load_master(_MasterConn([]))
        self.assertIn("monthly job", str(ctx.exception))

    def test_try_load_master_returns_master(self):
        master, reason = ir.try_load_master(_MasterConn([("RELIANCE", "INE002A01018")]))
        self.assertEqual(reason, "")
        self.assertIn("RELIANCE", master["by_symbol"])

    def test_try_load_master_never_raises(self):
        master, reason = ir.try_load_master(_MasterConn([]))
        self.assertIsNone(master)
        self.assertNotIn("\n", reason)
        self.assertIn("monthly job", reason)

    def test_try_load_master_without_conn(self):
        master, reason = ir.try_load_master(None)
        self.assertIsNone(master)
        self.assertIn("no database connection", reason)

    def test_try_load_master_query_error_is_caught(self):
        class _Broken:
            def execute(self, sql, params=()):
                raise OSError("connection dropped\nsecond line")

        master, reason = ir.try_load_master(_Broken())
        self.assertIsNone(master)
        self.assertEqual(reason, "OSError: connection dropped")


if __name__ == "__main__":
    unittest.main()
