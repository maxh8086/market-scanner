"""Offline checks on the llm-client adapters and the strict schema check.

The modules under test (llm_client/adapters/ollama.py, openai_compat.py,
anthropic_native.py and llm_client/schema_check.py) do not exist yet. Each test
imports its module inside the test body, so until they land every test fails
with ModuleNotFoundError and nothing else.

Assumed contracts (the executor must match them):
  adapters.ollama.build_payload(req) -> dict
  adapters.openai_compat.build_payload(req) -> dict
  adapters.openai_compat.build_url(origin) -> str
  adapters.anthropic_native.build_payload(req) -> dict
  schema_check.strict_check(reply, schema) -> None, raises
      llm_client.errors.ClientError with code "strict_check_missing_field:<name>"
where req is a dict with keys: model, messages, max_tokens, json_schema, options.
"""

import unittest

SCHEMA = {
    "type": "object",
    "required": ["events", "summary"],
    "properties": {
        "events": {"type": "array"},
        "summary": {"type": "string"},
    },
}


def _req(**overrides):
    req = {
        "model": "m",
        "messages": [{"role": "user", "content": "p"}],
        "max_tokens": 500,
        "json_schema": None,
        "options": None,
    }
    req.update(overrides)
    return req


class AnthropicNativeTest(unittest.TestCase):
    def test_anthropic_system_is_top_level(self):
        from llm_client.adapters.anthropic_native import build_payload

        req = _req(messages=[
            {"role": "system", "content": "S"},
            {"role": "user", "content": "U"},
        ])
        body = build_payload(req)
        self.assertEqual(body["system"], "S")
        self.assertEqual(body["messages"], [{"role": "user", "content": "U"}])
        for msg in body["messages"]:
            self.assertNotEqual(msg["role"], "system")

    def test_anthropic_max_tokens_from_request(self):
        from llm_client.adapters.anthropic_native import build_payload

        body = build_payload(_req(max_tokens=1400, json_schema=SCHEMA))
        self.assertEqual(body["max_tokens"], 1400)
        self.assertEqual(
            body["output_config"],
            {"format": {"type": "json_schema", "schema": SCHEMA}},
        )

    def test_anthropic_no_temperature(self):
        from llm_client.adapters.anthropic_native import build_payload

        body = build_payload(_req(temperature=0.1, top_p=0.9, top_k=40))
        for key in ("temperature", "top_p", "top_k"):
            self.assertNotIn(key, body)


class SchemaCheckTest(unittest.TestCase):
    def test_strict_check_missing_field_named(self):
        from llm_client.schema_check import strict_check
        from llm_client.errors import ClientError

        with self.assertRaises(ClientError) as ctx:
            strict_check({"events": []}, SCHEMA)
        self.assertEqual(ctx.exception.code, "strict_check_missing_field:summary")

    def test_null_counts_as_missing(self):
        from llm_client.schema_check import strict_check
        from llm_client.errors import ClientError

        with self.assertRaises(ClientError) as ctx:
            strict_check({"events": [], "summary": None}, SCHEMA)
        self.assertEqual(ctx.exception.code, "strict_check_missing_field:summary")


class PinnedPayloadTest(unittest.TestCase):
    def test_ollama_payload_matches_pinned_output(self):
        from llm_client.adapters.ollama import build_payload

        body = build_payload(_req(options={"num_ctx": 8192}))
        self.assertEqual(body, {
            "model": "m",
            "messages": [{"role": "user", "content": "p"}],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"num_ctx": 8192},
        })

        body = build_payload(_req())
        self.assertEqual(body, {
            "model": "m",
            "messages": [{"role": "user", "content": "p"}],
            "stream": False,
            "format": "json",
            "think": False,
        })

    def test_openai_compat_payload_matches_pinned_output(self):
        from llm_client.adapters.openai_compat import build_payload

        body = build_payload(_req())
        self.assertEqual(body, {
            "model": "m",
            "messages": [{"role": "user", "content": "p"}],
            "max_tokens": 500,
        })
        self.assertNotIn("think", body)

        body = build_payload(_req(json_schema=SCHEMA))
        self.assertEqual(body["response_format"], {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": SCHEMA, "strict": True},
        })


class CompatRouteTest(unittest.TestCase):
    def test_anthropic_compat_route_uses_openai_adapter(self):
        from llm_client.adapters import openai_compat

        url = openai_compat.build_url("https://api.anthropic.com/v1/")
        self.assertEqual(url, "https://api.anthropic.com/v1/chat/completions")

        body = openai_compat.build_payload(_req(json_schema=SCHEMA))
        self.assertIn("response_format", body)
        self.assertNotIn("output_config", body)


if __name__ == "__main__":
    unittest.main()
