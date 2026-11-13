"""llm-client registry refusals: unapproved provider and missing key record.

Contract under test (LC2, group "registry"):
- POST /v1/chat checks run in order and the first failure wins:
  provider approval, then key presence (keyed classes only), then key
  version, then origin, then route.
- Refusals of client state return 409 with JSON {"error": <code>}.
- No outbound provider call may happen when a refusal is returned.
"""

import unittest

import httpx

CHAT_TOKEN = "test-chat-token-registry"
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


class RegistryRefusalTests(unittest.TestCase):

    def test_unapproved_provider_refused(self):
        provider = {
            "provider_id": PROVIDER_ID,
            "class": "openai_compat",
            "origin": ORIGIN,
            "approved": False,
            "key_ref": KEY_REF,
            "key_version": 1,
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
        self.assertEqual(resp.json().get("error"), "provider_not_approved")
        self.assertEqual(
            len(recorder.calls), 0,
            "an unapproved provider must not produce any outbound call",
        )

    def test_missing_key_record_names_the_provider(self):
        provider = {
            "provider_id": PROVIDER_ID,
            "class": "openai_compat",
            "origin": ORIGIN,
            "approved": True,
            "key_ref": KEY_REF,
            "key_version": 1,
        }
        ui = FakeUi(provider=provider, key=None)
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = client.post("/v1/chat", headers=AUTH, json=_chat_body())

        self.assertEqual(resp.status_code, 409, resp.text)
        body = resp.json()
        self.assertEqual(body.get("error"), "key_missing")

        # The message must name the provider: use the 'detail' field when
        # the response carries one, otherwise the raw error text.
        message = body["detail"] if "detail" in body else resp.text
        self.assertIn(
            PROVIDER_ID, str(message),
            f"key_missing response must name provider {PROVIDER_ID!r}; got {message!r}",
        )

        self.assertEqual(
            len(recorder.calls), 0,
            "a missing key record must not produce any outbound call",
        )


if __name__ == "__main__":
    unittest.main()
