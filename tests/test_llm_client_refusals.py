"""llm-client refusals and provider-reply checks (decisions b, c, d, e, g and the
existing refusal order in llm_client/app.py).

Contract under test:
- Route mismatch: an openai_compat provider called with route "native" is
  409 route_mismatch with no outbound call.
- First failure wins: an unapproved provider is refused as
  provider_not_approved even when its key is also missing.
- A missing provider row is 409 provider_not_approved.
- Keyed classes (openai_compat, anthropic_native) refuse a non-https origin
  with 409 origin_not_https, before route_mismatch, with no outbound call and
  no key value in the body. Unkeyed ollama is not refused for scheme.
- Key records must carry a non-empty string value and an int key_version,
  else 409 key_missing. key_ref must equal "llm_key_" + provider_id, else
  409 key_missing.
- json_schema is sent as response_format with json_schema.strict == true.
- Provider replies that miss a required field are 502 strict_check_missing_field:<field>.
- Provider 400 is 502 provider_rejected:400 with the key absent from the body.
- Timeouts and connect errors use the status and code from llm_client/errors.py.
"""

import json
import unittest

import httpx

CHAT_TOKEN = "test-chat-token-refusals"
AUTH = {"Authorization": f"Bearer {CHAT_TOKEN}"}
PROVIDER_ID = "test_openai_provider"
KEY_REF = f"llm_key_{PROVIDER_ID}"
KEY_VALUE = "test-key-value-not-real"
ORIGIN = "https://llm.example.test"
OK_REPLY = {"choices": [{"message": {"content": "ok"}}]}


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
    """MockTransport handler that records every outbound provider request.

    It answers with the given status and body (dict for JSON, str for text),
    or raises the given exception instead of answering.
    """

    def __init__(self, status=200, body=OK_REPLY, exc=None):
        self.calls = []
        self._status = status
        self._body = body
        self._exc = exc

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self._exc is not None:
            raise self._exc
        if isinstance(self._body, str):
            return httpx.Response(self._status, text=self._body)
        return httpx.Response(self._status, json=self._body)


def _make_client(ui, recorder):
    from fastapi.testclient import TestClient

    from llm_client.app import create_app

    app = create_app(
        chat_token=CHAT_TOKEN,
        ui=ui,
        transport=httpx.MockTransport(recorder),
    )
    return TestClient(app)


def _provider(**changes):
    provider = {
        "provider_id": PROVIDER_ID,
        "class": "openai_compat",
        "origin": ORIGIN,
        "approved": True,
        "key_ref": KEY_REF,
        "key_version": 1,
    }
    provider.update(changes)
    return provider


def _key(**changes):
    key = {"value": KEY_VALUE, "origin": ORIGIN, "key_version": 1}
    key.update(changes)
    return key


def _chat_body(route="compat", json_schema=None):
    body = {
        "provider_id": PROVIDER_ID,
        "model": "test-model",
        "route": route,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 16,
    }
    if json_schema is not None:
        body["json_schema"] = json_schema
    return body


def _post(client, body):
    return client.post("/v1/chat", headers=AUTH, json=body)


class RouteMismatchTests(unittest.TestCase):

    def test_openai_compat_provider_with_native_route_is_409_route_mismatch(self):
        ui = FakeUi(provider=_provider(), key=_key())
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body(route="native"))

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json().get("error"), "route_mismatch")
        self.assertEqual(len(recorder.calls), 0)


class FirstFailureWinsTests(unittest.TestCase):

    def test_unapproved_provider_with_missing_key_reports_provider_not_approved(self):
        ui = FakeUi(provider=_provider(approved=False), key=None)
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body())

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json().get("error"), "provider_not_approved")
        self.assertEqual(len(recorder.calls), 0)


class ProviderRowMissingTests(unittest.TestCase):

    def test_missing_provider_row_is_409_provider_not_approved(self):
        ui = FakeUi(provider=None, key=_key())
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body())

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json().get("error"), "provider_not_approved")
        self.assertEqual(len(recorder.calls), 0)


class KeyedHttpOriginTests(unittest.TestCase):

    def test_keyed_http_origin_is_409_origin_not_https_with_no_outbound_call(self):
        http_origin = "http://api.example.test"
        ui = FakeUi(
            provider=_provider(origin=http_origin),
            key=_key(origin=http_origin),
        )
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body())

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json().get("error"), "origin_not_https")
        self.assertEqual(len(recorder.calls), 0)
        self.assertNotIn(KEY_VALUE, resp.text)


class UnkeyedOllamaSchemeTests(unittest.TestCase):

    def test_ollama_http_origin_is_not_refused_for_scheme(self):
        provider = {
            "provider_id": PROVIDER_ID,
            "class": "ollama",
            "origin": "http://ollama.example.test:11434",
            "approved": True,
        }
        ui = FakeUi(provider=provider, key=None)
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body(route="native"))

        self.assertNotEqual(resp.json().get("error"), "origin_not_https", resp.text)


class KeyRecordTests(unittest.TestCase):

    def test_empty_key_value_is_409_key_missing_with_no_outbound_call(self):
        ui = FakeUi(provider=_provider(), key=_key(value=""))
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body())

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json().get("error"), "key_missing")
        self.assertEqual(len(recorder.calls), 0)

    def test_key_version_missing_or_string_is_409_key_missing(self):
        missing = _key()
        del missing["key_version"]
        cases = {
            "missing": missing,
            "string": _key(key_version="1"),
        }
        for label, key in cases.items():
            with self.subTest(key_version=label):
                ui = FakeUi(provider=_provider(), key=key)
                recorder = Recorder()
                client = _make_client(ui, recorder)

                resp = _post(client, _chat_body())

                self.assertEqual(resp.status_code, 409, resp.text)
                self.assertEqual(resp.json().get("error"), "key_missing")
                self.assertEqual(len(recorder.calls), 0)

    def test_key_ref_not_matching_provider_id_is_409_key_missing(self):
        ui = FakeUi(provider=_provider(key_ref="test-key-ref"), key=_key())
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body())

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json().get("error"), "key_missing")
        self.assertEqual(len(recorder.calls), 0)


class StrictJsonSchemaTests(unittest.TestCase):

    def test_outbound_body_carries_response_format_with_strict_true(self):
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }
        ui = FakeUi(provider=_provider(), key=_key())
        recorder = Recorder()
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body(json_schema=schema))

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(recorder.calls), 1)
        sent = json.loads(recorder.calls[0].content)
        self.assertIn("response_format", sent)
        response_format = sent["response_format"]
        self.assertEqual(response_format.get("type"), "json_schema")
        json_schema = response_format.get("json_schema", {})
        self.assertIs(json_schema.get("strict"), True)
        self.assertEqual(json_schema.get("schema"), schema)
        self.assertIsInstance(json_schema.get("name"), str)
        self.assertTrue(json_schema.get("name"))


class StrictCheckTests(unittest.TestCase):

    def test_null_message_content_is_502_strict_check_missing_message_content(self):
        ui = FakeUi(provider=_provider(), key=_key())
        recorder = Recorder(body={"choices": [{"message": {"content": None}}]})
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body())

        self.assertEqual(resp.status_code, 502, resp.text)
        self.assertTrue(
            str(resp.json().get("error", "")).startswith(
                "strict_check_missing_field:message.content"
            ),
            resp.text,
        )

    def test_empty_choices_is_502_strict_check_missing_field_choices(self):
        ui = FakeUi(provider=_provider(), key=_key())
        recorder = Recorder(body={"choices": []})
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body())

        self.assertEqual(resp.status_code, 502, resp.text)
        self.assertEqual(resp.json().get("error"), "strict_check_missing_field:choices")


class ProviderRejectedTests(unittest.TestCase):

    def test_provider_400_is_502_provider_rejected_and_key_absent_from_body(self):
        ui = FakeUi(provider=_provider(), key=_key())
        recorder = Recorder(status=400, body=f"invalid api key: {KEY_VALUE}")
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body())

        self.assertEqual(resp.status_code, 502, resp.text)
        self.assertEqual(resp.json().get("error"), "provider_rejected:400")
        self.assertNotIn(KEY_VALUE, resp.text)


class ProviderTransportErrorTests(unittest.TestCase):

    def test_provider_timeout_uses_status_and_code_from_errors_module(self):
        from llm_client.errors import status_for

        ui = FakeUi(provider=_provider(), key=_key())
        recorder = Recorder(exc=httpx.ReadTimeout("timed out"))
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body())

        self.assertEqual(resp.status_code, status_for("provider_timeout"), resp.text)
        self.assertEqual(resp.json().get("error"), "provider_timeout")

    def test_provider_connect_error_uses_status_and_code_from_errors_module(self):
        from llm_client.errors import status_for

        ui = FakeUi(provider=_provider(), key=_key())
        recorder = Recorder(exc=httpx.ConnectError("connection refused"))
        client = _make_client(ui, recorder)

        resp = _post(client, _chat_body())

        self.assertEqual(resp.status_code, status_for("provider_unreachable"), resp.text)
        self.assertEqual(resp.json().get("error"), "provider_unreachable")


if __name__ == "__main__":
    unittest.main()
