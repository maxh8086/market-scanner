"""llm-client request validation (design decision f).

Contract under test:
- provider_id must match ^[a-z][a-z0-9_]{0,40}$, otherwise 422.
- model must be non-blank after strip and at most 200 chars. A blank model
  is refused as 422 with error model_not_set.
- messages must be a non-empty list, otherwise 422.
- max_tokens must be an int from 1 to 32768, otherwise 422.
- route must be "native" or "compat", otherwise 422.
- extra fields are 422.
Every refusal happens before any outbound provider call.
"""

import unittest

import httpx

CHAT_TOKEN = "test-chat-token-validation"
AUTH = {"Authorization": f"Bearer {CHAT_TOKEN}"}
PROVIDER_ID = "test-openai-provider"
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


def _chat_body(**changes):
    body = {
        "provider_id": PROVIDER_ID,
        "model": "test-model",
        "route": "compat",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 16,
    }
    body.update(changes)
    return body


class ProviderIdPatternTests(unittest.TestCase):

    def test_bad_provider_id_pattern_is_422_with_no_outbound_call(self):
        bad_ids = [
            "Bad_Provider",
            "Bad Provider",
            "-leading-dash",
            "openai-main",
            "1provider",
            "has.dot",
            "x" * 42,
        ]
        for bad_id in bad_ids:
            with self.subTest(provider_id=bad_id):
                ui = FakeUi(provider=None)
                recorder = Recorder()
                client = _make_client(ui, recorder)

                resp = client.post(
                    "/v1/chat", headers=AUTH, json=_chat_body(provider_id=bad_id),
                )

                self.assertEqual(resp.status_code, 422, resp.text)
                self.assertEqual(len(recorder.calls), 0)


class ModelValidationTests(unittest.TestCase):

    def test_blank_model_is_422_model_not_set(self):
        for blank in ["", "   ", "\t"]:
            with self.subTest(model=repr(blank)):
                ui = FakeUi(provider=None)
                recorder = Recorder()
                client = _make_client(ui, recorder)

                resp = client.post("/v1/chat", headers=AUTH, json=_chat_body(model=blank))

                self.assertEqual(resp.status_code, 422, resp.text)
                self.assertEqual(resp.json().get("error"), "model_not_set", resp.text)
                self.assertEqual(len(recorder.calls), 0)

    def test_model_over_200_chars_is_422_with_no_outbound_call(self):
        ui = FakeUi(provider=None)
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = client.post("/v1/chat", headers=AUTH, json=_chat_body(model="m" * 201))

        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertEqual(len(recorder.calls), 0)


class MessagesValidationTests(unittest.TestCase):

    def test_empty_messages_is_422_with_no_outbound_call(self):
        ui = FakeUi(provider=None)
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = client.post("/v1/chat", headers=AUTH, json=_chat_body(messages=[]))

        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertEqual(len(recorder.calls), 0)


class MaxTokensValidationTests(unittest.TestCase):

    def test_max_tokens_out_of_range_is_422_with_no_outbound_call(self):
        for value in [0, 40000]:
            with self.subTest(max_tokens=value):
                ui = FakeUi(provider=None)
                recorder = Recorder()
                client = _make_client(ui, recorder)

                resp = client.post(
                    "/v1/chat", headers=AUTH, json=_chat_body(max_tokens=value),
                )

                self.assertEqual(resp.status_code, 422, resp.text)
                self.assertEqual(len(recorder.calls), 0)


class RouteValidationTests(unittest.TestCase):

    def test_route_other_is_422_with_no_outbound_call(self):
        ui = FakeUi(provider=None)
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = client.post("/v1/chat", headers=AUTH, json=_chat_body(route="other"))

        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertEqual(len(recorder.calls), 0)


class ExtraFieldValidationTests(unittest.TestCase):

    def test_extra_base_url_field_is_422_with_no_outbound_call(self):
        ui = FakeUi(provider=None)
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = client.post(
            "/v1/chat",
            headers=AUTH,
            json=_chat_body(base_url="https://evil.example.test"),
        )

        self.assertEqual(resp.status_code, 422, resp.text)
        self.assertEqual(len(recorder.calls), 0)


if __name__ == "__main__":
    unittest.main()
