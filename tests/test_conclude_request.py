"""Offline checks on the request body built by conclude._request_body for each backend."""

import unittest

from scanner import conclude
from scanner.llm import LLMConfig


class ConcludeOllamaBodyTest(unittest.TestCase):
    def setUp(self):
        cfg = LLMConfig(api="ollama", model="m", base_url="http://x:11434")
        self.body = conclude._request_body(cfg, "u", 500, None)

    def test_ollama_body_is_non_streaming_and_thinking_off(self):
        self.assertIs(self.body["stream"], False)
        self.assertIs(self.body["think"], False)

    def test_ollama_body_carries_schema_as_format(self):
        self.assertIsInstance(self.body["format"], dict)
        self.assertIn("type", self.body["format"])

    def test_ollama_body_has_options(self):
        self.assertIn("temperature", self.body["options"])
        self.assertIn("num_ctx", self.body["options"])

    def test_ollama_body_has_no_openai_only_keys(self):
        self.assertNotIn("response_format", self.body)
        self.assertNotIn("max_tokens", self.body)


class ConcludeOpenAIBodyTest(unittest.TestCase):
    def test_openai_body_keeps_response_format_and_max_tokens(self):
        body = conclude._request_body(LLMConfig(api="openai", model="m"), "u", 500, None)
        self.assertIn("response_format", body)
        self.assertIn("max_tokens", body)
        self.assertNotIn("think", body)


if __name__ == "__main__":
    unittest.main()
