"""Origin-binding tests for the llm-client service (LC2 contract).

The service must:
- refuse any caller-supplied base_url (pydantic extra=forbid -> 400/422),
- never send a provider key to an origin other than the one the key record
  was registered for (scheme+host+port; the path is ignored),
- never echo the key value in a response body.

Outbound provider calls are intercepted with a recording httpx.MockTransport,
so no real network traffic happens and the transport log is the ground truth
for "no outbound call was made".
"""

import unittest


KEY_VALUE = "sk-test-not-real"
CHAT_TOKEN = "test-chat-token-origin"
PROVIDER_ID = "openai_main"
KEY_REF = "llm_key_openai_main"


class FakeUi:
    """Stands in for the UI-side registry the app reads provider and key records from."""

    def __init__(self, provider, key):
        self._provider = provider
        self._key = key

    def get_provider(self, provider_id):
        if provider_id == self._provider["provider_id"]:
            return dict(self._provider)
        return None

    def get_key(self, key_ref):
        if key_ref == self._provider["key_ref"]:
            return dict(self._key)
        return None


class RecordingTransport:
    """Records every outbound request and answers with a fake completion."""

    def __init__(self):
        self.requests = []

    def handler(self, request):
        import httpx

        self.requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "cmpl-test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )


def _make_client(provider_origin, key_origin, transport):
    from fastapi.testclient import TestClient

    from llm_client.app import create_app

    provider = {
        "provider_id": PROVIDER_ID,
        "class": "openai_compat",
        "origin": provider_origin,
        "approved": True,
        "key_ref": KEY_REF,
        "key_version": 1,
    }
    key = {
        "value": KEY_VALUE,
        "origin": key_origin,
        "key_version": 1,
    }
    ui = FakeUi(provider, key)
    app = create_app(chat_token=CHAT_TOKEN, ui=ui, transport=transport)
    return TestClient(app)


def _chat_body(**extra):
    body = {
        "provider_id": PROVIDER_ID,
        "model": "gpt-test",
        "route": "compat",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 16,
    }
    body.update(extra)
    return body


def _auth_headers():
    return {"Authorization": "Bearer " + CHAT_TOKEN}


class OriginBindingTests(unittest.TestCase):

    def test_base_url_field_is_rejected_and_no_call_made(self):
        import httpx

        transport_log = RecordingTransport()
        mock = httpx.MockTransport(transport_log.handler)
        client = _make_client("https://api.openai.com", "https://api.openai.com", mock)

        resp = client.post(
            "/v1/chat",
            json=_chat_body(base_url="https://evil.example.com"),
            headers=_auth_headers(),
        )

        self.assertIn(resp.status_code, (400, 422), resp.text)
        self.assertEqual(
            transport_log.requests,
            [],
            "a request carrying base_url must not trigger any outbound call",
        )

    def test_key_not_sent_when_origin_differs(self):
        import httpx

        transport_log = RecordingTransport()
        mock = httpx.MockTransport(transport_log.handler)
        client = _make_client(
            "https://api.openai.com",
            "https://evil.example.com",
            mock,
        )

        resp = client.post("/v1/chat", json=_chat_body(), headers=_auth_headers())

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json().get("error"), "origin_mismatch", resp.text)
        self.assertEqual(
            transport_log.requests,
            [],
            "the key must not be sent to any origin when origins differ",
        )
        self.assertNotIn(
            KEY_VALUE,
            resp.text,
            "the key value must never appear in a response body",
        )

    def test_origin_check_ignores_path(self):
        import httpx

        transport_log = RecordingTransport()
        mock = httpx.MockTransport(transport_log.handler)
        client = _make_client(
            "https://api.openai.com/v1",
            "https://api.openai.com",
            mock,
        )

        resp = client.post("/v1/chat", json=_chat_body(), headers=_auth_headers())

        self.assertNotEqual(
            resp.json().get("error"),
            "origin_mismatch",
            "matching scheme+host+port must pass the origin check regardless of path",
        )
        self.assertEqual(
            len(transport_log.requests),
            1,
            "with matching origins the request proceeds to the provider",
        )
        outbound = transport_log.requests[0]
        self.assertEqual(outbound.url.host, "api.openai.com")
        self.assertEqual(outbound.url.path, "/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
