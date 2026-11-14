"""Offline tests for the broker login internal API (ui/app/broker_login.py, phase 1, Kite).

Covers the login-url, exchange and status endpoints, the single-use state, the server-only
gate, and the broker-secret rules of GET /internal/secrets/{name} (ui/app/internal_secrets.py).
No network: _kite_exchange and requests.post are patched. Secrets go through an in-memory
fake of scanner.app_secrets (get_value, get_meta, put); the DB connection is a MagicMock, as in
tests/test_service_secrets.py.
"""
import datetime as dt
import hashlib
import logging
import os
import tempfile
import unittest
import urllib.parse
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scanner import app_secrets
from ui.app import broker_login, internal_secrets

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 14, 12, 0, tzinfo=UTC)  # 17:30 IST
FRESH_ISSUED = dt.datetime(2026, 11, 14, 0, 45, tzinfo=UTC)  # 06:15 IST, expires 15 Nov 00:30 UTC
EXPIRED_ISSUED = dt.datetime(2026, 11, 13, 12, 0, tzinfo=UTC)  # expired 14 Nov 00:30 UTC
EXPIRES_AT = "2026-11-15T00:30:00+00:00"
MASTER = b"\x00" * 32

COLLECTOR_TOKEN = "tok-collector-111"
LLM_TOKEN = "tok-llm-222"
SERVER_TOKEN = "tok-server-333"
TOKEN_ENVS = {
    "COLLECTOR_TOKEN_FILE": ("collector_token", COLLECTOR_TOKEN),
    "LLM_CLIENT_TOKEN_FILE": ("llm_client_token", LLM_TOKEN),
    "SERVER_TOKEN_FILE": ("server_token", SERVER_TOKEN),
}
SECRETS = ("ACCESS-TOKEN-XYZ", "KEY-ABC", "SECRET-DEF", "REQ-TOKEN-1")


class _CollectHandler(logging.Handler):
    """Keeps every formatted log record so a test can search them."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())
        self.lines.append(self.format(record))


class FakeStore:
    """In-memory stand-in for app_secrets.get_value / get_meta / put."""

    def __init__(self):
        self.values = {}
        self.meta = {}
        self.decrypted = []
        self.puts = []

    def seed(self, name, value, issued_at):
        self.values[name] = value
        self.meta[name] = {"name": name, "last4": value[-4:], "updated_at": issued_at}

    def get_value(self, conn, key, name):
        self.decrypted.append(name)
        if name not in self.values:
            raise app_secrets.SecretNotFound(name)
        return self.values[name]

    def get_meta(self, conn, name):
        return self.meta.get(name)

    def put(self, conn, key, name, value, *, created_on, expires_on, updated_by):
        self.puts.append({"name": name, "created_on": created_on,
                          "expires_on": expires_on, "updated_by": updated_by})
        self.seed(name, value, NOW)


class BrokerLoginBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = {}
        for var, (filename, token) in TOKEN_ENVS.items():
            path = os.path.join(tmp.name, filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(token)
            env[var] = path
        self._patch(patch.dict(os.environ, env))

        self._patch(patch("ui.app.broker_login.load_master_key", return_value=MASTER))
        self._patch(patch("ui.app.internal_secrets.load_master_key", return_value=MASTER))
        self._patch(patch("scanner.pg.db.connect"))
        self.store = FakeStore()
        self._patch(patch.object(app_secrets, "get_value", side_effect=self.store.get_value))
        self._patch(patch.object(app_secrets, "get_meta", side_effect=self.store.get_meta))
        self._patch(patch.object(app_secrets, "put", side_effect=self.store.put))
        self._patch(patch.object(broker_login, "_utc_now", return_value=NOW))
        self._patch(patch.object(internal_secrets, "_utc_now", return_value=NOW))
        self.mono = [1000.0]
        self._patch(patch.object(broker_login, "_clock", new=lambda: self.mono[0]))
        self._patch(patch.object(broker_login, "_STATES", new=broker_login._StateStore()))
        self.real_kite_exchange = broker_login._kite_exchange
        self.exchange = self._patch(
            patch.object(broker_login, "_kite_exchange", return_value="ACCESS-TOKEN-XYZ"))

        self.store.values["kite_api_key"] = "KEY-ABC"
        self.store.values["kite_api_secret"] = "SECRET-DEF"

        app = FastAPI()
        app.include_router(internal_secrets.router)
        app.include_router(broker_login.router)
        self.client = TestClient(app)

    def _patch(self, p):
        mock = p.start()
        self.addCleanup(p.stop)
        return mock

    def _call(self, method, path, *, token=SERVER_TOKEN, json_body=None, params=None):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        return self.client.request(method, path, headers=headers, json=json_body, params=params)

    def _login_state(self, profile="default"):
        resp = self._call("POST", "/internal/broker/kite/login-url",
                          json_body={"profile_id": profile})
        self.assertEqual(resp.status_code, 200, resp.text)
        query = urllib.parse.urlsplit(resp.json()["url"]).query
        return urllib.parse.parse_qs(urllib.parse.parse_qs(query)["redirect_params"][0])["state"][0]

    def _exchange(self, state, request_token="REQ-TOKEN-1"):
        return self._call("POST", "/internal/broker/kite/exchange",
                          json_body={"request_token": request_token, "state": state})

    def _capture_logs(self):
        handler = _CollectHandler()
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, old_level)
        return handler


class LoginUrl(BrokerLoginBase):
    def test_url_carries_api_key_and_single_use_state(self):
        resp = self._call("POST", "/internal/broker/kite/login-url",
                          json_body={"profile_id": "default"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("no-store", resp.headers.get("Cache-Control", "").lower())
        parts = urllib.parse.urlsplit(resp.json()["url"])
        self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}",
                         "https://kite.zerodha.com/connect/login")
        query = urllib.parse.parse_qs(parts.query)
        self.assertEqual(query["v"], ["3"])
        self.assertEqual(query["api_key"], ["KEY-ABC"])
        state = urllib.parse.parse_qs(query["redirect_params"][0])["state"][0]
        self.assertGreaterEqual(len(state), 40)

    def test_default_profile_falls_back_to_global_key(self):
        self.store.values["kite_api_key"] = "GLOBAL-KEY"
        resp = self._call("POST", "/internal/broker/kite/login-url", json_body={})
        self.assertEqual(resp.status_code, 200)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(resp.json()["url"]).query)
        self.assertEqual(query["api_key"], ["GLOBAL-KEY"])

    def test_profile_key_is_preferred_and_other_profiles_do_not_fall_back(self):
        self.store.values["broker_work_kite_api_key"] = "WORK-KEY"
        resp = self._call("POST", "/internal/broker/kite/login-url",
                          json_body={"profile_id": "work"})
        self.assertEqual(resp.status_code, 200)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(resp.json()["url"]).query)
        self.assertEqual(query["api_key"], ["WORK-KEY"])

        resp = self._call("POST", "/internal/broker/kite/login-url",
                          json_body={"profile_id": "other"})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json(), {"detail": "api key not configured"})

    def test_no_api_key_configured_is_409(self):
        self.store.values.clear()
        resp = self._call("POST", "/internal/broker/kite/login-url", json_body={})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json(), {"detail": "api key not configured"})

    def test_invalid_profile_is_400(self):
        for profile in ("Work", "work_1", "", "a" * 17, "1work"):
            with self.subTest(profile=profile):
                resp = self._call("POST", "/internal/broker/kite/login-url",
                                  json_body={"profile_id": profile})
                self.assertEqual(resp.status_code, 400)

    def test_other_broker_is_404_for_every_route(self):
        self.exchange.reset_mock()
        for method, path, body in (
            ("POST", "/internal/broker/zerodha/login-url", {}),
            ("POST", "/internal/broker/zerodha/exchange", {"request_token": "R", "state": "S"}),
            ("GET", "/internal/broker/zerodha/status", None),
        ):
            with self.subTest(path=path):
                resp = self._call(method, path, json_body=body)
                self.assertEqual(resp.status_code, 404)
                self.assertEqual(resp.json(), {"detail": "broker not supported"})
        self.exchange.assert_not_called()


class Exchange(BrokerLoginBase):
    def test_valid_state_is_single_use(self):
        state = self._login_state()
        first = self._exchange(state)
        self.assertEqual(first.status_code, 200)
        second = self._exchange(state)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json(), {"detail": "invalid or expired state"})
        self.exchange.assert_called_once_with("KEY-ABC", "REQ-TOKEN-1", "SECRET-DEF")

    def test_state_is_valid_for_just_under_ten_minutes(self):
        state = self._login_state()
        self.mono[0] += 599
        self.assertEqual(self._exchange(state).status_code, 200)

    def test_state_expires_after_ten_minutes(self):
        state = self._login_state()
        self.mono[0] += 601
        resp = self._exchange(state)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"detail": "invalid or expired state"})
        self.exchange.assert_not_called()

    def test_unknown_or_other_broker_state_never_calls_broker(self):
        resp = self._exchange("state-that-was-never-issued")
        self.assertEqual(resp.status_code, 400)

        other = broker_login._STATES.issue("default", "upstox")
        resp = self._exchange(other)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"detail": "invalid or expired state"})
        self.exchange.assert_not_called()

    def test_stores_token_with_computed_expiry_and_returns_only_expiry(self):
        state = self._login_state()
        resp = self._exchange(state)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"profile_id": "default", "expires_at": EXPIRES_AT})
        self.assertNotIn("ACCESS-TOKEN-XYZ", resp.text)
        self.assertEqual(self.store.values["broker_default_kite_access_token"], "ACCESS-TOKEN-XYZ")
        self.assertEqual(len(self.store.puts), 1)
        put = self.store.puts[0]
        self.assertEqual(put["created_on"], dt.date(2026, 11, 14))
        self.assertEqual(put["expires_on"], dt.date(2026, 11, 15))
        self.assertEqual(put["updated_by"], "broker_login")

    def test_broker_failure_is_502_and_stores_nothing(self):
        self.exchange.side_effect = RuntimeError("upstream echoed REQ-TOKEN-1 SECRET-DEF")
        state = self._login_state()
        resp = self._exchange(state)
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json(), {"detail": "broker exchange failed"})
        for secret in ("REQ-TOKEN-1", "SECRET-DEF", "KEY-ABC"):
            self.assertNotIn(secret, resp.text)
        self.assertNotIn("broker_default_kite_access_token", self.store.values)
        self.assertEqual(self._exchange(state).status_code, 400)

    def test_missing_fields_is_400_and_does_not_consume_state(self):
        state = self._login_state()
        resp = self._call("POST", "/internal/broker/kite/exchange", json_body={"state": state})
        self.assertEqual(resp.status_code, 400)
        self.exchange.assert_not_called()
        self.assertEqual(self._exchange(state).status_code, 200)

    def test_missing_api_secret_is_409_and_no_broker_call(self):
        self.store.values.pop("kite_api_secret")
        state = self._login_state()
        resp = self._exchange(state)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json(), {"detail": "api key not configured"})
        self.exchange.assert_not_called()

    def test_kite_exchange_posts_checksum_and_reads_access_token(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"status": "success", "data": {"access_token": "ACC-1"}}
        with patch("ui.app.broker_login.requests.post", return_value=response) as post:
            self.exchange.side_effect = self.real_kite_exchange
            resp = self._exchange(self._login_state())
        self.assertEqual(resp.status_code, 200)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.kite.trade/session/token")
        self.assertEqual(kwargs["data"]["checksum"],
                         hashlib.sha256(b"KEY-ABCREQ-TOKEN-1SECRET-DEF").hexdigest())
        self.assertEqual(kwargs["headers"], {"X-Kite-Version": "3"})
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(self.store.values["broker_default_kite_access_token"], "ACC-1")

    def test_kite_exchange_failure_message_never_carries_broker_body(self):
        response = MagicMock(status_code=400)
        response.text = "bad REQ-TOKEN-1 SECRET-DEF"
        with patch("ui.app.broker_login.requests.post", return_value=response):
            with self.assertRaises(broker_login.BrokerExchangeError) as ctx:
                self.real_kite_exchange("KEY-ABC", "REQ-TOKEN-1", "SECRET-DEF")
        self.assertEqual(str(ctx.exception), "kite session call failed")

    def test_state_store_never_holds_more_than_the_cap(self):
        store = broker_login._StateStore()
        with patch.object(broker_login, "_clock", new=lambda: 0.0):
            for _ in range(broker_login.STATE_MAX + 5):
                store.issue("default", "kite")
        self.assertLessEqual(len(store._items), broker_login.STATE_MAX)


class Status(BrokerLoginBase):
    def test_not_stored_is_not_connected(self):
        resp = self._call("GET", "/internal/broker/kite/status", params={"profile_id": "default"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"connected": False, "expires_at": None})

    def test_unexpired_token_is_connected_and_never_returned_or_decrypted(self):
        self.store.seed("broker_default_kite_access_token", "ACCESS-TOKEN-XYZ", FRESH_ISSUED)
        resp = self._call("GET", "/internal/broker/kite/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"connected": True, "expires_at": EXPIRES_AT})
        self.assertNotIn("ACCESS-TOKEN-XYZ", resp.text)
        self.assertNotIn("broker_default_kite_access_token", self.store.decrypted)

    def test_expired_token_is_not_connected(self):
        self.store.seed("broker_default_kite_access_token", "ACCESS-TOKEN-XYZ", EXPIRED_ISSUED)
        resp = self._call("GET", "/internal/broker/kite/status")
        self.assertEqual(resp.json(), {"connected": False, "expires_at": None})

    def test_profile_query_defaults_to_default_and_rejects_bad_ids(self):
        self.store.seed("broker_work_kite_access_token", "ACCESS-TOKEN-XYZ", FRESH_ISSUED)
        self.assertEqual(self._call("GET", "/internal/broker/kite/status").json()["connected"],
                         False)
        self.assertEqual(self._call("GET", "/internal/broker/kite/status",
                                    params={"profile_id": "work"}).json()["connected"], True)
        self.assertEqual(self._call("GET", "/internal/broker/kite/status",
                                    params={"profile_id": "Work"}).status_code, 400)


class ServerOnlyGate(BrokerLoginBase):
    KITE_ROUTES = (
        ("POST", "/internal/broker/kite/login-url", {"profile_id": "default"}),
        ("POST", "/internal/broker/kite/exchange", {"request_token": "R", "state": "S"}),
        ("GET", "/internal/broker/kite/status", None),
    )
    UPSTOX_ROUTES = (
        ("POST", "/internal/broker/upstox/login-url", {"profile_id": "default"}),
        ("POST", "/internal/broker/upstox/exchange", {"code": "C", "state": "S"}),
        ("GET", "/internal/broker/upstox/status", None),
    )
    ROUTES = KITE_ROUTES + UPSTOX_ROUTES

    def test_collector_and_llm_client_get_403(self):
        for method, path, body in self.ROUTES:
            for token in (COLLECTOR_TOKEN, LLM_TOKEN):
                with self.subTest(path=path, token=token):
                    resp = self._call(method, path, token=token, json_body=body)
                    self.assertEqual(resp.status_code, 403)
                    self.assertIn("no-store", resp.headers.get("Cache-Control", "").lower())
        self.assertEqual(broker_login._STATES._items, {})
        self.exchange.assert_not_called()

    def test_bad_or_missing_token_is_401(self):
        for method, path, body in self.ROUTES:
            for token in ("tok-wrong", None):
                with self.subTest(path=path, token=token):
                    resp = self._call(method, path, token=token, json_body=body)
                    self.assertEqual(resp.status_code, 401)
        self.assertEqual(broker_login._STATES._items, {})


class BrokerSecretNames(BrokerLoginBase):
    """GET /internal/secrets/{name} for broker_* names."""

    def _get(self, name, token=SERVER_TOKEN):
        return self._call("GET", f"/internal/secrets/{name}", token=token)

    def test_server_reads_unexpired_access_token_with_no_store(self):
        self.store.seed("broker_default_kite_access_token", "ACCESS-TOKEN-XYZ", FRESH_ISSUED)
        resp = self._get("broker_default_kite_access_token")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"name": "broker_default_kite_access_token",
                                       "value": "ACCESS-TOKEN-XYZ"})
        self.assertIn("no-store", resp.headers.get("Cache-Control", "").lower())

    def test_expired_access_token_is_404_without_decrypting(self):
        self.store.seed("broker_default_kite_access_token", "ACCESS-TOKEN-XYZ", EXPIRED_ISSUED)
        resp = self._get("broker_default_kite_access_token")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("broker_default_kite_access_token", self.store.decrypted)
        self.assertNotIn("ACCESS-TOKEN-XYZ", resp.text)

    def test_access_token_not_stored_is_404(self):
        resp = self._get("broker_default_kite_access_token")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.store.decrypted, [])

    def test_server_reads_broker_api_key(self):
        self.store.values["broker_work_kite_api_key"] = "WORK-KEY"
        resp = self._get("broker_work_kite_api_key")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["value"], "WORK-KEY")

    def test_api_secret_names_are_403_for_every_service(self):
        self.store.values["broker_default_kite_api_secret"] = "SECRET-DEF"
        for token in (SERVER_TOKEN, COLLECTOR_TOKEN, LLM_TOKEN):
            with self.subTest(token=token):
                resp = self._get("broker_default_kite_api_secret", token=token)
                self.assertEqual(resp.status_code, 403)
        self.assertNotIn("broker_default_kite_api_secret", self.store.decrypted)

    def test_collector_and_llm_client_get_403_for_broker_names(self):
        self.store.seed("broker_default_kite_access_token", "ACCESS-TOKEN-XYZ", FRESH_ISSUED)
        self.store.values["broker_default_kite_api_key"] = "KEY-ABC"
        for token in (COLLECTOR_TOKEN, LLM_TOKEN):
            for name in ("broker_default_kite_access_token", "broker_default_kite_api_key"):
                with self.subTest(token=token, name=name):
                    self.assertEqual(self._get(name, token=token).status_code, 403)
        self.assertEqual(self.store.decrypted, [])

    def test_broker_responses_and_logs_never_carry_secret_values(self):
        handler = self._capture_logs()
        self.store.seed("broker_default_kite_access_token", "ACCESS-TOKEN-XYZ", FRESH_ISSUED)
        self.assertEqual(self._get("broker_default_kite_access_token", token="tok-wrong").status_code,
                         401)
        self.assertEqual(self._get("broker_default_kite_api_secret").status_code, 403)
        self.assertEqual(self._get("broker_default_kite_access_token").status_code, 200)
        joined = "\n".join(handler.lines)
        self.assertIn("status 200", joined)
        self.assertNotIn("ACCESS-TOKEN-XYZ", joined)
        self.assertNotIn(SERVER_TOKEN, joined)


class NoSecretInLogsOrErrors(BrokerLoginBase):
    def test_flow_logs_and_error_bodies_are_clean(self):
        handler = self._capture_logs()
        bodies = []

        state = self._login_state()
        self.exchange.side_effect = RuntimeError("upstream said REQ-TOKEN-1 SECRET-DEF")
        failed = self._exchange(state)
        bodies.append(failed.text)
        self.assertEqual(failed.status_code, 502)

        self.exchange.side_effect = None
        bad = self._exchange("BAD-STATE-VALUE")
        bodies.append(bad.text)
        self.assertEqual(bad.status_code, 400)

        good = self._exchange(self._login_state())
        self.assertEqual(good.status_code, 200)
        self.assertEqual(self._call("GET", "/internal/broker/kite/status").status_code, 200)

        joined = "\n".join(handler.lines)
        self.assertIn("status 502", joined)
        for secret in SECRETS + (state, "BAD-STATE-VALUE", SERVER_TOKEN):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, joined)
                for body in bodies:
                    self.assertNotIn(secret, body)


UP_KEY = "UP-KEY-123"
UP_SECRET = "UP-SECRET-456"
UP_CODE = "UP-CODE-789"
UP_TOKEN = "UP-ACCESS-XYZ"
UP_REDIRECT = "http://127.0.0.1:8081/api/broker/upstox/callback"
UP_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
UP_DIALOG_URL = "https://api.upstox.com/v2/login/authorization/dialog"
# Upstox tokens expire at the next 03:30 IST. Issued 17:30 IST on 14 Nov -> 03:30 IST 15 Nov.
UP_EXPIRES = dt.datetime(2026, 11, 14, 22, 0, tzinfo=UTC).isoformat()


class UpstoxSetup(BrokerLoginBase):
    """Upstox credentials per profile only, no network: _upstox_exchange is patched by default."""

    def setUp(self):
        super().setUp()
        self._patch(patch.dict(os.environ))
        os.environ.pop("UPSTOX_REDIRECT_URI", None)
        self.real_upstox_exchange = broker_login._upstox_exchange
        self.upstox_exchange = self._patch(
            patch.object(broker_login, "_upstox_exchange", return_value=UP_TOKEN))
        self.store.values["broker_default_upstox_api_key"] = UP_KEY
        self.store.values["broker_default_upstox_api_secret"] = UP_SECRET

    def _upstox_state(self, profile="default"):
        resp = self._call("POST", "/internal/broker/upstox/login-url",
                          json_body={"profile_id": profile})
        self.assertEqual(resp.status_code, 200, resp.text)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(resp.json()["url"]).query)
        return query["state"][0]

    def _upstox_exchange_call(self, state, code=UP_CODE):
        return self._call("POST", "/internal/broker/upstox/exchange",
                          json_body={"code": code, "state": state})

    def _get(self, name, token=SERVER_TOKEN):
        return self._call("GET", f"/internal/secrets/{name}", token=token)


class UpstoxLoginUrl(UpstoxSetup):
    def test_url_is_dialog_with_profile_key_redirect_and_single_use_state(self):
        resp = self._call("POST", "/internal/broker/upstox/login-url",
                          json_body={"profile_id": "default"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("no-store", resp.headers.get("Cache-Control", "").lower())
        parts = urllib.parse.urlsplit(resp.json()["url"])
        self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}", UP_DIALOG_URL)
        query = urllib.parse.parse_qs(parts.query)
        self.assertEqual(set(query), {"response_type", "client_id", "redirect_uri", "state"})
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["client_id"], [UP_KEY])
        self.assertEqual(query["redirect_uri"], [UP_REDIRECT])
        self.assertGreaterEqual(len(query["state"][0]), 40)
        self.assertNotIn("KEY-ABC", resp.text)
        self.assertNotIn(UP_SECRET, resp.text)

    def test_redirect_uri_is_read_from_env_at_call_time(self):
        os.environ["UPSTOX_REDIRECT_URI"] = "https://example.test/upstox/cb"
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(
            self._call("POST", "/internal/broker/upstox/login-url",
                       json_body={}).json()["url"]).query)
        self.assertEqual(query["redirect_uri"], ["https://example.test/upstox/cb"])

    def test_blank_redirect_env_uses_the_default(self):
        os.environ["UPSTOX_REDIRECT_URI"] = ""
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(
            self._call("POST", "/internal/broker/upstox/login-url",
                       json_body={}).json()["url"]).query)
        self.assertEqual(query["redirect_uri"], [UP_REDIRECT])

    def test_no_global_fallback_for_upstox(self):
        # The kite global names are present; upstox must not read them.
        self.store.values.pop("broker_default_upstox_api_key")
        resp = self._call("POST", "/internal/broker/upstox/login-url", json_body={})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json(), {"detail": "api key not configured"})
        self.assertEqual(self.store.decrypted, ["broker_default_upstox_api_key"])

    def test_profile_key_is_used_for_that_profile_only(self):
        self.store.values["broker_work_upstox_api_key"] = "UP-WORK-KEY"
        resp = self._call("POST", "/internal/broker/upstox/login-url",
                          json_body={"profile_id": "work"})
        self.assertEqual(resp.status_code, 200)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(resp.json()["url"]).query)
        self.assertEqual(query["client_id"], ["UP-WORK-KEY"])
        resp = self._call("POST", "/internal/broker/upstox/login-url",
                          json_body={"profile_id": "other"})
        self.assertEqual(resp.status_code, 409)

    def test_login_url_needs_only_the_key_not_the_secret(self):
        self.store.values.pop("broker_default_upstox_api_secret")
        self.assertEqual(self._call("POST", "/internal/broker/upstox/login-url",
                                    json_body={}).status_code, 200)


class UpstoxExchange(UpstoxSetup):
    def test_stores_token_with_upstox_expiry_and_returns_only_expiry(self):
        state = self._upstox_state()
        resp = self._upstox_exchange_call(state)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"profile_id": "default", "expires_at": UP_EXPIRES})
        self.assertNotIn(UP_TOKEN, resp.text)
        self.assertNotIn(UP_CODE, resp.text)
        self.assertEqual(self.store.values["broker_default_upstox_access_token"], UP_TOKEN)
        self.assertEqual(len(self.store.puts), 1)
        put = self.store.puts[0]
        self.assertEqual(put["name"], "broker_default_upstox_access_token")
        self.assertEqual(put["created_on"], dt.date(2026, 11, 14))
        self.assertEqual(put["expires_on"], dt.date(2026, 11, 15))
        self.assertEqual(put["updated_by"], "broker_login")
        self.upstox_exchange.assert_called_once_with(UP_KEY, UP_SECRET, UP_CODE, UP_REDIRECT)
        self.exchange.assert_not_called()

    def test_upstox_exchange_posts_form_body_and_reads_access_token(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"access_token": "UP-ACC-1", "token_type": "bearer"}
        self.upstox_exchange.side_effect = self.real_upstox_exchange
        with patch("ui.app.broker_login.requests.post", return_value=response) as post:
            state = self._upstox_state()
            resp = self._upstox_exchange_call(state)
        self.assertEqual(resp.status_code, 200)
        args, kwargs = post.call_args
        self.assertEqual(args[0], UP_TOKEN_URL)
        self.assertEqual(kwargs["data"], {
            "code": UP_CODE, "client_id": UP_KEY, "client_secret": UP_SECRET,
            "redirect_uri": UP_REDIRECT, "grant_type": "authorization_code"})
        self.assertEqual(kwargs["headers"], {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(self.store.values["broker_default_upstox_access_token"], "UP-ACC-1")

    def test_upstox_exchange_failure_message_never_carries_broker_body(self):
        response = MagicMock(status_code=403)
        response.text = f"denied {UP_CODE} {UP_SECRET}"
        with patch("ui.app.broker_login.requests.post", return_value=response):
            with self.assertRaises(broker_login.BrokerExchangeError) as ctx:
                self.real_upstox_exchange(UP_KEY, UP_SECRET, UP_CODE, UP_REDIRECT)
        self.assertEqual(str(ctx.exception), "upstox token call failed")

    def test_upstox_exchange_without_access_token_raises(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"errors": []}
        with patch("ui.app.broker_login.requests.post", return_value=response):
            with self.assertRaises(broker_login.BrokerExchangeError) as ctx:
                self.real_upstox_exchange(UP_KEY, UP_SECRET, UP_CODE, UP_REDIRECT)
        self.assertEqual(str(ctx.exception), "upstox token call returned no token")

    def test_broker_failure_is_502_stores_nothing_and_consumes_state(self):
        self.upstox_exchange.side_effect = RuntimeError(f"upstream echoed {UP_CODE} {UP_SECRET}")
        state = self._upstox_state()
        resp = self._upstox_exchange_call(state)
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json(), {"detail": "broker exchange failed"})
        for secret in (UP_CODE, UP_SECRET, UP_KEY):
            self.assertNotIn(secret, resp.text)
        self.assertNotIn("broker_default_upstox_access_token", self.store.values)
        self.assertEqual(self._upstox_exchange_call(state).status_code, 400)

    def test_state_is_single_use_and_expires_after_ten_minutes(self):
        state = self._upstox_state()
        self.assertEqual(self._upstox_exchange_call(state).status_code, 200)
        second = self._upstox_exchange_call(state)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json(), {"detail": "invalid or expired state"})
        self.assertEqual(self.upstox_exchange.call_count, 1)

        stale = self._upstox_state()
        self.mono[0] += 601
        resp = self._upstox_exchange_call(stale)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.upstox_exchange.call_count, 1)

    def test_states_do_not_cross_brokers(self):
        kite_state = self._login_state()
        resp = self._upstox_exchange_call(kite_state)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"detail": "invalid or expired state"})
        self.upstox_exchange.assert_not_called()

        upstox_state = self._upstox_state()
        resp = self._call("POST", "/internal/broker/kite/exchange",
                          json_body={"request_token": "REQ-TOKEN-1", "state": upstox_state})
        self.assertEqual(resp.status_code, 400)
        self.exchange.assert_not_called()

    def test_kite_body_on_upstox_route_and_upstox_body_on_kite_route_are_400(self):
        state = self._upstox_state()
        resp = self._call("POST", "/internal/broker/upstox/exchange",
                          json_body={"request_token": "REQ-TOKEN-1", "state": state})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"detail": "invalid request"})
        self.upstox_exchange.assert_not_called()
        # The 400 does not consume the state.
        self.assertEqual(self._upstox_exchange_call(state).status_code, 200)

        kite_state = self._login_state()
        resp = self._call("POST", "/internal/broker/kite/exchange",
                          json_body={"code": UP_CODE, "state": kite_state})
        self.assertEqual(resp.status_code, 400)
        self.exchange.assert_not_called()
        self.assertEqual(self._exchange(kite_state).status_code, 200)

    def test_missing_api_key_or_secret_is_409_and_no_broker_call(self):
        state = self._upstox_state()
        self.store.values.pop("broker_default_upstox_api_key")
        resp = self._upstox_exchange_call(state)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json(), {"detail": "api key not configured"})
        self.upstox_exchange.assert_not_called()

        self.store.values["broker_default_upstox_api_key"] = UP_KEY
        state = self._upstox_state()
        self.store.values.pop("broker_default_upstox_api_secret")
        resp = self._upstox_exchange_call(state)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json(), {"detail": "api key not configured"})
        self.upstox_exchange.assert_not_called()


class UpstoxStatus(UpstoxSetup):
    def test_not_stored_is_not_connected(self):
        resp = self._call("GET", "/internal/broker/upstox/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"connected": False, "expires_at": None})

    def test_unexpired_token_is_connected_with_0330_ist_expiry(self):
        self.store.seed("broker_default_upstox_access_token", UP_TOKEN, FRESH_ISSUED)
        resp = self._call("GET", "/internal/broker/upstox/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"connected": True, "expires_at": UP_EXPIRES})
        self.assertNotIn(UP_TOKEN, resp.text)
        self.assertNotIn("broker_default_upstox_access_token", self.store.decrypted)

    def test_expired_token_is_not_connected(self):
        self.store.seed("broker_default_upstox_access_token", UP_TOKEN, EXPIRED_ISSUED)
        resp = self._call("GET", "/internal/broker/upstox/status")
        self.assertEqual(resp.json(), {"connected": False, "expires_at": None})

    def test_kite_token_does_not_count_for_upstox_and_the_reverse(self):
        self.store.seed("broker_default_kite_access_token", "ACCESS-TOKEN-XYZ", FRESH_ISSUED)
        self.assertEqual(self._call("GET", "/internal/broker/upstox/status").json()["connected"],
                         False)
        self.assertEqual(self._call("GET", "/internal/broker/kite/status").json()["connected"],
                         True)
        self.store.seed("broker_default_upstox_access_token", UP_TOKEN, FRESH_ISSUED)
        self.store.meta.pop("broker_default_kite_access_token")
        self.assertEqual(self._call("GET", "/internal/broker/kite/status").json()["connected"],
                         False)


class UpstoxSecretNames(UpstoxSetup):
    """GET /internal/secrets/{name} for broker_default_upstox_* names."""

    def test_server_reads_upstox_access_token_and_api_key(self):
        self.store.seed("broker_default_upstox_access_token", UP_TOKEN, FRESH_ISSUED)
        resp = self._get("broker_default_upstox_access_token")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"name": "broker_default_upstox_access_token",
                                       "value": UP_TOKEN})
        self.assertIn("no-store", resp.headers.get("Cache-Control", "").lower())
        resp = self._get("broker_default_upstox_api_key")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["value"], UP_KEY)

    def test_expired_upstox_access_token_is_404_without_decrypting(self):
        self.store.seed("broker_default_upstox_access_token", UP_TOKEN, EXPIRED_ISSUED)
        resp = self._get("broker_default_upstox_access_token")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("broker_default_upstox_access_token", self.store.decrypted)
        self.assertNotIn(UP_TOKEN, resp.text)

    def test_upstox_api_secret_is_403_for_every_service(self):
        for token in (SERVER_TOKEN, COLLECTOR_TOKEN, LLM_TOKEN):
            with self.subTest(token=token):
                self.assertEqual(self._get("broker_default_upstox_api_secret", token=token)
                                 .status_code, 403)
        self.assertNotIn("broker_default_upstox_api_secret", self.store.decrypted)

    def test_collector_and_llm_client_get_403_for_upstox_names(self):
        self.store.seed("broker_default_upstox_access_token", UP_TOKEN, FRESH_ISSUED)
        for token in (COLLECTOR_TOKEN, LLM_TOKEN):
            for name in ("broker_default_upstox_access_token", "broker_default_upstox_api_key"):
                with self.subTest(token=token, name=name):
                    self.assertEqual(self._get(name, token=token).status_code, 403)
        self.assertEqual(self.store.decrypted, [])

    def test_upstox_flow_logs_and_bodies_are_clean(self):
        handler = self._capture_logs()
        bodies = []

        state = self._upstox_state()
        self.upstox_exchange.side_effect = RuntimeError(f"upstream said {UP_CODE} {UP_SECRET}")
        failed = self._upstox_exchange_call(state)
        bodies.append(failed.text)
        self.assertEqual(failed.status_code, 502)

        self.upstox_exchange.side_effect = None
        bad = self._upstox_exchange_call("BAD-UP-STATE")
        bodies.append(bad.text)
        self.assertEqual(bad.status_code, 400)

        good_state = self._upstox_state()
        self.assertEqual(self._upstox_exchange_call(good_state).status_code, 200)
        self.assertEqual(self._call("GET", "/internal/broker/upstox/status").status_code, 200)

        joined = "\n".join(handler.lines)
        self.assertIn("status 200", joined)
        self.assertIn("status 502", joined)
        for secret in (UP_CODE, UP_SECRET, UP_KEY, UP_TOKEN, state, good_state,
                       "BAD-UP-STATE", SERVER_TOKEN):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, joined)
                for body in bodies:
                    self.assertNotIn(secret, body)


if __name__ == "__main__":
    unittest.main()
