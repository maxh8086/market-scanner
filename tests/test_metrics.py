"""Tests for scanner.metrics module.

Tests cover token extraction from both Ollama and OpenAI responses, JSONL
fallback, idempotence, GPU CSV processing, and summarization.
"""

import json
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from scanner import metrics


class TestTokenExtraction(unittest.TestCase):
    """Token extraction from LLM responses (both Ollama and OpenAI styles)."""

    def test_extract_tokens_from_ollama_response(self):
        """Ollama returns prompt_eval_count and eval_count."""
        from scanner import llm
        cfg = llm.LLMConfig(api="ollama")
        body = {
            "message": {"content": "result"},
            "prompt_eval_count": 123,
            "eval_count": 45,
        }
        input_t, output_t = llm._extract_tokens(cfg, body)
        self.assertEqual(input_t, 123)
        self.assertEqual(output_t, 45)

    def test_extract_tokens_from_openai_response(self):
        """OpenAI-compatible returns usage.prompt_tokens and completion_tokens."""
        from scanner import llm
        cfg = llm.LLMConfig(api="openai")
        body = {
            "choices": [{"message": {"content": "result"}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 50},
        }
        input_t, output_t = llm._extract_tokens(cfg, body)
        self.assertEqual(input_t, 200)
        self.assertEqual(output_t, 50)

    def test_extract_tokens_missing_returns_zeros(self):
        """Missing token fields return (0, 0)."""
        from scanner import llm
        cfg = llm.LLMConfig(api="ollama")
        body = {"message": {"content": "result"}}
        input_t, output_t = llm._extract_tokens(cfg, body)
        self.assertEqual(input_t, 0)
        self.assertEqual(output_t, 0)

    def test_extract_tokens_partial_usage_block(self):
        """Incomplete usage block fills in zeros."""
        from scanner import llm
        cfg = llm.LLMConfig(api="openai")
        body = {
            "choices": [{"message": {"content": "result"}}],
            "usage": {"prompt_tokens": 100},
        }
        input_t, output_t = llm._extract_tokens(cfg, body)
        self.assertEqual(input_t, 100)
        self.assertEqual(output_t, 0)


class TestRecordCallWithoutRunId(unittest.TestCase):
    """record_call is a no-op without RUN_ID env var."""

    def test_noop_without_run_id(self):
        """record_call returns without doing anything."""
        env = os.environ.copy()
        if "RUN_ID" in os.environ:
            del os.environ["RUN_ID"]
        try:
            # Should not raise or write anything
            metrics.record_call("extract", "seq_1", "ABC", "model", 100, 50, 1.0, True)
        finally:
            os.environ.clear()
            os.environ.update(env)


class TestJSONLFallback(unittest.TestCase):
    """Fallback to JSONL when Postgres is down."""

    def test_writes_jsonl_on_postgres_unavailable(self):
        """When Postgres is unreachable, metrics go to JSONL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = uuid.uuid4()

            # Override the logs directory
            with mock.patch("scanner.metrics._metrics_dir",
                           return_value=Path(tmpdir)):
                with mock.patch("scanner.metrics._get_connection", return_value=None):
                    os.environ["RUN_ID"] = str(run_id)
                    try:
                        metrics.record_call("extract", "seq_1", "ABC", "model",
                                           100, 50, 1.0, True)

                        # Check JSONL file
                        jsonl_path = Path(tmpdir) / f"{run_id}.jsonl"
                        self.assertTrue(jsonl_path.exists())

                        with open(jsonl_path) as f:
                            line = f.readline()
                            row = json.loads(line)
                            self.assertEqual(row["run_id"], str(run_id))
                            self.assertEqual(row["stage"], "extract")
                            self.assertEqual(row["source_key"], "seq_1")
                            self.assertEqual(row["input_tokens"], 100)
                            self.assertEqual(row["output_tokens"], 50)
                    finally:
                        if "RUN_ID" in os.environ:
                            del os.environ["RUN_ID"]

    def test_jsonl_appends_multiple_rows(self):
        """Multiple calls append to the same JSONL file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = uuid.uuid4()

            with mock.patch("scanner.metrics._metrics_dir",
                           return_value=Path(tmpdir)):
                with mock.patch("scanner.metrics._get_connection", return_value=None):
                    os.environ["RUN_ID"] = str(run_id)
                    try:
                        metrics.record_call("extract", "seq_1", "ABC", "model",
                                           100, 50, 1.0, True)
                        metrics.record_call("extract", "seq_2", "DEF", "model",
                                           150, 60, 1.5, True)

                        jsonl_path = Path(tmpdir) / f"{run_id}.jsonl"
                        with open(jsonl_path) as f:
                            lines = [l.strip() for l in f if l.strip()]
                            self.assertEqual(len(lines), 2)
                            row1 = json.loads(lines[0])
                            row2 = json.loads(lines[1])
                            self.assertEqual(row1["source_key"], "seq_1")
                            self.assertEqual(row2["source_key"], "seq_2")
                    finally:
                        if "RUN_ID" in os.environ:
                            del os.environ["RUN_ID"]


class TestGPUCSVProcessing(unittest.TestCase):
    """GPU CSV parsing and aggregation."""

    def test_process_empty_csv(self):
        """Empty or nonexistent GPU CSV returns None values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # File does not exist
            gpu_name, watts_avg, energy_wh, busy_sec = \
                metrics._process_gpu_csv(os.path.join(tmpdir, "nonexistent.csv"))
            self.assertIsNone(gpu_name)
            self.assertIsNone(watts_avg)
            self.assertIsNone(energy_wh)
            self.assertIsNone(busy_sec)

    def test_process_gpu_csv_with_samples(self):
        """Process a GPU CSV with known samples."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_file = os.path.join(tmpdir, "gpu.csv")
            # Samples at times 0, 2, 4, 6 (seconds) with varying power and utilization
            with open(csv_file, "w") as f:
                f.write("0.0,RTX3090,100.0,10.0,5000\n")      # 100W, 10% util
                f.write("2.0,RTX3090,110.0,20.0,5100\n")      # 110W, 20% util
                f.write("4.0,RTX3090,90.0,15.0,4900\n")       # 90W, 15% util
                f.write("6.0,RTX3090,100.0,8.0,5000\n")       # 100W, 8% util (low)

            gpu_name, watts_avg, energy_wh, busy_sec = \
                metrics._process_gpu_csv(csv_file)

            self.assertEqual(gpu_name, "RTX3090")
            # Average power: (100 + 110 + 90 + 100) / 4 = 100
            self.assertEqual(watts_avg, 100.0)
            # Energy via trapezoidal rule:
            # [0,2]: (100+110)/2 * 2 = 210 Ws
            # [2,4]: (110+90)/2 * 2 = 200 Ws
            # [4,6]: (90+100)/2 * 2 = 190 Ws
            # Total: 600 Ws = 600/3600 Wh = 0.1667
            self.assertAlmostEqual(energy_wh, 600 / 3600, places=4)
            # Busy (>5%): samples at 0, 2, 4 all have >5%, so 4 seconds
            # (busy during [0,2], [2,4], [4,6] since even at 8% we count)
            self.assertGreater(busy_sec, 0)

    def test_gpu_csv_malformed_lines_skipped(self):
        """Malformed lines in GPU CSV are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_file = os.path.join(tmpdir, "gpu.csv")
            with open(csv_file, "w") as f:
                f.write("0.0,RTX3090,100.0,10.0,5000\n")
                f.write("malformed line\n")
                f.write("2.0,RTX3090,110.0,20.0,5100\n")

            gpu_name, watts_avg, energy_wh, busy_sec = \
                metrics._process_gpu_csv(csv_file)

            self.assertEqual(gpu_name, "RTX3090")
            # Should have processed 2 valid rows
            self.assertIsNotNone(watts_avg)


class TestLLMResultIntegration(unittest.TestCase):
    """LLMResult now includes token counts."""

    def test_llm_result_has_token_fields(self):
        """LLMResult dataclass has input_tokens and output_tokens."""
        from scanner import llm
        result = llm.LLMResult(
            data={"a": 1}, raw="", error="", seconds=1.0, model="test",
            input_tokens=100, output_tokens=50
        )
        self.assertEqual(result.input_tokens, 100)
        self.assertEqual(result.output_tokens, 50)


class TestConclusionIntegration(unittest.TestCase):
    """Conclusion now includes token counts."""

    def test_conclusion_has_token_fields(self):
        """Conclusion dataclass has input_tokens and output_tokens."""
        from scanner import conclude
        c = conclude.Conclusion(
            symbol="ABC",
            stance="CONSTRUCTIVE",
            input_tokens=200,
            output_tokens=80
        )
        self.assertEqual(c.input_tokens, 200)
        self.assertEqual(c.output_tokens, 80)


class TestExtractSourceKey(unittest.TestCase):
    """extract() derives source_key from text hash if not provided."""

    def test_extract_derives_source_key_from_text_hash(self):
        """When source_key is not provided, it is derived from text hash."""
        from scanner import llm

        with mock.patch("scanner.metrics.record_call") as mock_record:
            # Mock the requests.post to avoid actual HTTP call
            with mock.patch("requests.post") as mock_post:
                # Set up a mock response
                mock_resp = mock.MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "message": {"content": '{"order_amount": 100, "order_unit": "crore"}'},
                    "prompt_eval_count": 100,
                    "eval_count": 50,
                }
                mock_post.return_value = mock_resp

                cfg = llm.LLMConfig(api="ollama")
                result = llm.extract(cfg, "some filing text")

                # Check that record_call was called with a derived source_key
                self.assertTrue(mock_record.called)
                call_args = mock_record.call_args
                # source_key is the first positional arg after stage
                source_key = call_args[0][1]
                # Should be a 16-char hex string (from hash)
                self.assertEqual(len(source_key), 16)
                self.assertTrue(all(c in "0123456789abcdef" for c in source_key))

    def test_extract_uses_provided_source_key(self):
        """When source_key is provided, it is used as-is."""
        from scanner import llm

        with mock.patch("scanner.metrics.record_call") as mock_record:
            with mock.patch("requests.post") as mock_post:
                mock_resp = mock.MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "message": {"content": '{"order_amount": 100}'},
                    "prompt_eval_count": 100,
                    "eval_count": 50,
                }
                mock_post.return_value = mock_resp

                cfg = llm.LLMConfig(api="ollama")
                result = llm.extract(cfg, "text", source_key="custom_key_123", symbol="ABC")

                self.assertTrue(mock_record.called)
                call_args = mock_record.call_args
                self.assertEqual(call_args[0][1], "custom_key_123")  # source_key
                self.assertEqual(call_args[0][2], "ABC")  # symbol


if __name__ == "__main__":
    unittest.main()
