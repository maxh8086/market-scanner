"""LC6 cutover checks (design docs/designs/home-events-t4f-design.md, section 7).

- bench_extract.py must refuse --url and --api (benchmarks use the active
  provider only, O8 / M-25) while still accepting --model.
- The llm-client default model tag is the Qwen3.5 Ollama tag (BL-4).

Everything is mocked. No network, no database.
"""
import contextlib
import io
import unittest
from unittest import mock

import bench_extract
from scanner import llm

EXPECTED_DEFAULT_MODEL = "hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K"


def _run_bench(argv):
    """Run bench_extract.main with every external touch point mocked.

    Health is reported as down, so a parser that accepts the argv returns 1
    without reaching a server. The mocks are returned for inspection.
    """
    with mock.patch.object(bench_extract.docstore, "open_db") as open_db, \
            mock.patch.object(bench_extract, "pick", return_value=([], [], [])), \
            mock.patch.object(bench_extract.llm, "health",
                              return_value=(False, "mocked down")) as health, \
            mock.patch.object(bench_extract.llm, "extract") as extract, \
            contextlib.redirect_stderr(io.StringIO()), \
            contextlib.redirect_stdout(io.StringIO()):
        open_db.return_value = mock.MagicMock()
        result = bench_extract.main(argv)
    return result, health, extract


class TestBenchRefusesUrlOverride(unittest.TestCase):
    def test_bench_refuses_url_override(self):
        for argv in (["--url", "http://127.0.0.1:9999"],
                     ["--api", "ollama"],
                     ["--url", "http://127.0.0.1:9999", "--api", "openai"]):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as cm:
                    _run_bench(argv)
                self.assertNotEqual(cm.exception.code, 0)

        # --model is still accepted and is passed through to the config.
        with self.subTest(argv=["--model", "qwen-test-tag"]):
            result, health, _extract = _run_bench(["--model", "qwen-test-tag"])
            self.assertEqual(result, 1)
            health.assert_called_once()
            cfg = health.call_args[0][0]
            self.assertEqual(cfg.model, "qwen-test-tag")


class TestDefaultModelTag(unittest.TestCase):
    def test_default_model_is_qwen_tag(self):
        self.assertEqual(llm.LLMConfig().model, EXPECTED_DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()
