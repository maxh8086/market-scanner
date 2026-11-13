"""llm-client key freshness: a stale key record after a rollback is refused.

Contract under test (LC2, group "registry"):
- The key record's key_version must equal the provider's key_version.
  A mismatch returns 409 {"error": "key_stale_version"} and no outbound
  provider call is made.
"""

import unittest

import httpx

CHAT_TOKEN = "test-chat-token-freshness"
AUTH = {"Authorization": f"Bearer {CHAT_TOKEN}"}
PROVIDER_ID = "test_openai_provider"
KEY_REF = "llm_key_test_openai_provider"
ORIGIN = "https://llm.example.test"


class FakeUi:
    """Stands in for the ui registry the app reads provider and key records from."""

    def __init__(self, provider=None, key=None):
        self._provider = provider
        self._key = key
        self.provider_reads = []
        self.key_reads = []

    def get_provider(self, provider_id):
        self.provider_reads.append(provider_id)
        return None if self._provider is None else dict(self._provider)

    def get_key(self, key_ref):
        self.key_reads.append(key_ref)
        return None if self._key is None else dict(self._key)


class Recorder:
    """MockTransport handler that records every outbound provider request."""

    def __init__(self):
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})


def _make_client(ui, recorder):
    from fastapi.testclient import TestClient

    from llm_client.app import create_app

    app = create_app(
        chat_token=CHAT_TOKEN,
        ui=ui,
        transport=httpx.MockTransport(recorder),
    )
    return TestClient(app)


def _chat_body():
    return {
        "provider_id": PROVIDER_ID,
        "model": "test-model",
        "route": "compat",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 16,
    }


class StaleKeyVersionTests(unittest.TestCase):

    def test_stale_record_version_refused_after_rollback(self):
        # Provider was rolled forward to key_version 2, but the key record
        # the client can read is still at version 1 (stale after rollback).
        provider = {
            "provider_id": PROVIDER_ID,
            "class": "openai_compat",
            "origin": ORIGIN,
            "approved": True,
            "key_ref": KEY_REF,
            "key_version": 2,
        }
        key = {
            "value": "test-key-value-not-real",
            "origin": ORIGIN,
            "key_version": 1,
        }
        ui = FakeUi(provider=provider, key=key)
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = client.post("/v1/chat", headers=AUTH, json=_chat_body())

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json().get("error"), "key_stale_version")
        self.assertEqual(
            len(recorder.calls), 0,
            "a stale key version must not produce any outbound call",
        )


if __name__ == "__main__":
    unittest.main()
