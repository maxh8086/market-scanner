"""Bearer-token and health-endpoint tests for the llm_client service (LC2 auth group).

These tests exercise only the HTTP surface of llm_client.app.create_app.
No outbound provider calls are made: the FakeUi returns None for every lookup,
and none of the tested paths reach a provider.
"""

import unittest

from fastapi.testclient import TestClient

from llm_client.app import create_app

TEST_CHAT_TOKEN = "test-token-123"  # test value only, defined in this file


class FakeUi:
    """Stand-in for the UI registry. Both lookups report nothing found."""

    def get_provider(self, provider_id):
        return None

    def get_key(self, key_ref):
        return None


CHAT_BODY = {
    "provider_id": "test-provider",
    "model": "test-model",
    "route": "native",
    "messages": [{"role": "user", "content": "ping"}],
    "max_tokens": 16,
}


class LlmClientAuthTests(unittest.TestCase):
    def setUp(self):
        app = create_app(chat_token=TEST_CHAT_TOKEN, ui=FakeUi())
        self.client = TestClient(app)

    def test_chat_without_token_is_401_token_missing(self):
        resp = self.client.post("/v1/chat", json=CHAT_BODY)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json(), {"error": "token_missing"})

    def test_chat_with_wrong_token_is_401_token_invalid(self):
        resp = self.client.post(
            "/v1/chat",
            json=CHAT_BODY,
            headers={"Authorization": "Bearer not-the-right-token"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json().get("error"), "token_invalid")

    def test_healthz_has_no_urls_or_keys(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "ok")
        text = resp.text
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        self.assertNotIn(TEST_CHAT_TOKEN, text)
        self.assertNotIn("sk-", text)
        self.assertNotIn("Bearer", text)


if __name__ == "__main__":
    unittest.main()
