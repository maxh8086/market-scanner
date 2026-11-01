import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import enrich
from scanner import docstore, graph, llm


class StageLlmTests(unittest.TestCase):
    def test_parallel_extraction_stores_every_doc_from_main_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = docstore.open_db(Path(tmp) / "d.json")
            for i in range(12):
                docstore.put_filing(db, {"seq_id": str(i), "symbol": f"S{i}", "kind": "guidance",
                                         "raw_text": "text", "an_date": "2026-01-01"})
            threads = set()
            main = threading.get_ident()

            def fake_extract(cfg, text, kind, **_kw):
                threads.add(threading.get_ident())
                return llm.LLMResult(data={"counterparty": "X"}, raw="{}", error="", seconds=0.01,
                                     model="m", prompt_version="v")

            real_put = docstore.put_extraction
            writers = []

            def spy(*a, **k):
                writers.append(threading.get_ident())
                return real_put(*a, **k)

            cfg = llm.LLMConfig(base_url="http://x", model="m", api="openai")
            with mock.patch.object(llm, "health", return_value=(True, "ok")), \
                 mock.patch.object(llm, "extract", side_effect=fake_extract), \
                 mock.patch.object(docstore, "put_extraction", side_effect=spy):
                enrich.stage_llm(db, cfg, workers=4)
            self.assertEqual(len(db.table(docstore.EXTRACTIONS).all()), 12)
            self.assertEqual(set(writers), {main})
            self.assertGreater(len(threads), 1)
            db.close()


class ConnectTests(unittest.TestCase):
    def test_reads_neo4j_auth(self):
        seen = {}

        class FakeGDB:
            @staticmethod
            def driver(uri, auth):
                seen.update(uri=uri, auth=auth)
                return object()

        fake_mod = mock.MagicMock(GraphDatabase=FakeGDB)
        env = {"NEO4J_AUTH": "neo4j/s3cret", "NEO4J_URI": "bolt://neo4j:7687"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.dict("sys.modules", {"neo4j": fake_mod}):
            graph.connect()
        self.assertEqual(seen, {"uri": "bolt://neo4j:7687", "auth": ("neo4j", "s3cret")})

    def test_missing_password_exits(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.dict("sys.modules", {"neo4j": mock.MagicMock()}):
            with self.assertRaises(SystemExit):
                graph.connect()


if __name__ == "__main__":
    unittest.main()
