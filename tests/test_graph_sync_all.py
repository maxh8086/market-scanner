"""graph_sync._all reads a docstore table on both backends, offline.

Regression: _all called db.table(name).all(), which is TinyDB only. On MongoDB
the collection raised "'Collection' object is not callable" and the graph-load
step failed on every run.
"""
from __future__ import annotations

import unittest

import graph_sync
from scanner import mongo


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *_args, **_kwargs):
        return [dict(d) for d in self._docs]

    def __call__(self, *_args, **_kwargs):  # mirrors pymongo: calling a collection is an error
        raise TypeError("'Collection' object is not callable")


class _FakeMongo(mongo.MongoDB):
    def __init__(self, tables):  # skip the real client and indexes
        self.db = {name: _FakeCollection(docs) for name, docs in tables.items()}


class _FakeTinyTable:
    def __init__(self, docs):
        self._docs = docs

    def all(self):
        return list(self._docs)


class _FakeTiny:
    def __init__(self, tables):
        self._tables = {name: _FakeTinyTable(docs) for name, docs in tables.items()}

    def table(self, name):
        return self._tables[name]


class AllRowsTest(unittest.TestCase):
    def test_mongo_rows_are_plain_dicts_without_object_id(self):
        db = _FakeMongo({"filings": [{"_id": object(), "seq_id": "1", "kind": "x"}]})
        rows = graph_sync._all(db, "filings")
        self.assertEqual(rows, [{"seq_id": "1", "kind": "x"}])

    def test_mongo_empty_table_gives_empty_list(self):
        db = _FakeMongo({"conclusions": []})
        self.assertEqual(graph_sync._all(db, "conclusions"), [])

    def test_tinydb_rows_still_work(self):
        db = _FakeTiny({"filings": [{"seq_id": "7"}]})
        self.assertEqual(graph_sync._all(db, "filings"), [{"seq_id": "7"}])


if __name__ == "__main__":
    unittest.main()
