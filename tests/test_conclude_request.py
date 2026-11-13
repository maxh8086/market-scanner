"""Request body for the conclude call, sent to llm-client (design section 4.5)."""
import unittest

from scanner import conclude
from scanner.llm import LLMConfig


class ConcludeBodyTest(unittest.TestCase):
    def setUp(self):
        cfg = LLMConfig(model="m", base_url="http://x:8000", provider_id="ollama", route="native")
        self.body = conclude._request_body(cfg, "u", 500, None)

    def test_body_is_the_llm_client_contract(self):
        self.assertEqual(self.body["provider_id"], "ollama")
        self.assertEqual(self.body["route"], "native")
        self.assertEqual(self.body["model"], "m")
        self.assertEqual(self.body["max_tokens"], 500)

    def test_messages_are_system_then_user(self):
        self.assertEqual([m["role"] for m in self.body["messages"]], ["system", "user"])
        self.assertEqual(self.body["messages"][1]["content"], "u")

    def test_schema_travels_as_json_schema(self):
        self.assertIsInstance(self.body["json_schema"], dict)
        self.assertIn("type", self.body["json_schema"])

    def test_no_provider_specific_keys(self):
        for key in ("stream", "think", "format", "response_format"):
            self.assertNotIn(key, self.body)

    def test_options_carry_temperature_and_num_ctx(self):
        self.assertIn("temperature", self.body["options"])
        self.assertIn("num_ctx", self.body["options"])


if __name__ == "__main__":
    unittest.main()
