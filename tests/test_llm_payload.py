"""Offline checks on the request payload sent to the Ollama and OpenAI-style endpoints."""

import unittest

from scanner import llm
from scanner.llm import LLMConfig


class OllamaPayloadTest(unittest.TestCase):
    def test_ollama_payload_disables_thinking_and_requests_json(self):
        body = llm._payload(LLMConfig(api="ollama", model="m"), "p")
        self.assertIs(body["think"], False)
        self.assertEqual(body["format"], "json")
        self.assertIs(body["stream"], False)

    def test_openai_payload_has_no_think_key(self):
        body = llm._payload(LLMConfig(api="openai", model="m"), "p")
        self.assertNotIn("think", body)

    def test_ollama_endpoint_is_api_chat(self):
        cfg = LLMConfig(api="ollama", base_url="http://x:11434")
        self.assertEqual(cfg.endpoint, "http://x:11434/api/chat")


if __name__ == "__main__":
    unittest.main()
