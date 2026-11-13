"""Offline tests for service-to-service secret delivery (secrets S5).

Covers the internal endpoint in ui/app/internal_secrets.py, the client in
scanner/service_client.py, the collector and first-run wiring, and the
`service-token collector` CLI. No network: urllib.request.urlopen and the
app_secrets / DB functions are patched. Modules that do not exist yet are
imported inside each test so that each test fails on its own.
"""
import contextlib
import io
import logging
import os
import re
import secrets
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytz

from scanner import app_secrets
from scanner import secrets_cli


# ---------------------------------------------------------------------------
# A. Internal endpoint: GET /internal/secrets/{name}
# ---------------------------------------------------------------------------

class _CollectHandler(logging.Handler):
    """Keeps every formatted log record so a test can search them."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())
        self.lines.append(self.format(record))


class InternalSecretsEndpoint(unittest.TestCase):
    TOKEN = "tok-test-123"
    MASTER = b"\x00" * 32

    def _patch(self, target, **kwargs):
        p = patch(target, **kwargs)
        mock = p.start()
        self.addCleanup(p.stop)
        return mock

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.token_file = os.path.join(tmp.name, "collector_token")
        with open(self.token_file, "w", encoding="utf-8") as f:
            f.write(self.TOKEN)

        self._patch("ui.app.internal_secrets.load_master_key", return_value=self.MASTER)
        self.get_value = self._patch("ui.app.internal_secrets.app_secrets.get_value",
                                     return_value="VALUE-XYZ")
        self.db_connect = self._patch("scanner.pg.db.connect")
        env = patch.dict(os.environ, {"COLLECTOR_TOKEN_FILE": self.token_file})
        env.start()
        self.addCleanup(env.stop)

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from ui.app import internal_secrets

        app = FastAPI()
        app.include_router(internal_secrets.router)
        return TestClient(app)

    def _get(self, name, token=TOKEN):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        return self._client().get(f"/internal/secrets/{name}", headers=headers)

    def test_no_authorization_header_is_401(self):
        resp = self._get("upstox_analytics_token", token=None)
        self.assertEqual(resp.status_code, 401)
        self.get_value.assert_not_called()

    def test_wrong_bearer_token_is_401(self):
        resp = self._get("upstox_analytics_token", token="tok-wrong")
        self.assertEqual(resp.status_code, 401)
        self.get_value.assert_not_called()

    def test_name_outside_collector_allowlist_is_403(self):
        resp = self._get("kite_api_key")
        self.assertEqual(resp.status_code, 403)
        self.get_value.assert_not_called()

    def test_allowed_name_not_stored_is_404(self):
        self.get_value.side_effect = app_secrets.SecretNotFound("upstox_analytics_token")
        resp = self._get("upstox_analytics_token")
        self.assertEqual(resp.status_code, 404)

    def test_allowed_name_returns_value_with_no_store(self):
        resp = self._get("upstox_analytics_token")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"name": "upstox_analytics_token", "value": "VALUE-XYZ"})
        self.assertIn("no-store", resp.headers.get("Cache-Control", "").lower())

    def test_missing_token_file_is_503_even_with_header(self):
        missing = os.path.join(os.path.dirname(self.token_file), "does-not-exist")
        with patch.dict(os.environ, {"COLLECTOR_TOKEN_FILE": missing}):
            resp = self._get("upstox_analytics_token")
        self.assertEqual(resp.status_code, 503)
        self.get_value.assert_not_called()

    def test_secret_value_never_reaches_logs(self):
        handler = _CollectHandler()
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, old_level)

        resp = self._get("upstox_analytics_token")
        self.assertEqual(resp.status_code, 200)
        joined = "\n".join(handler.lines)
        self.assertNotIn("VALUE-XYZ", joined)

    # llm-client service token (LC2). Same request pattern as the collector tests above.
    # Assumption: the llm-client token file is named by LLM_CLIENT_TOKEN_FILE. The collector
    # token from setUp is left unchanged, and the llm-client token is a different value.
    LLM_TOKEN = "tok-llm-client-456"
    LLM_TOKEN_ENV = "LLM_CLIENT_TOKEN_FILE"

    def _use_llm_client_token(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "llm_client_token")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.LLM_TOKEN)
        env = patch.dict(os.environ, {self.LLM_TOKEN_ENV: path})
        env.start()
        self.addCleanup(env.stop)
        return self.LLM_TOKEN

    def test_llm_client_token_cannot_read_upstox_token(self):
        token = self._use_llm_client_token()
        resp = self._get("upstox_analytics_token", token=token)
        self.assertEqual(resp.status_code, 403)
        self.get_value.assert_not_called()

    def test_llm_client_token_reads_only_llm_key_names(self):
        token = self._use_llm_client_token()
        allowed = self._get("llm_key_openai", token=token)
        self.assertTrue(200 <= allowed.status_code < 300,
                        f"expected 2xx for llm_key_openai, got {allowed.status_code}")
        denied = self._get("upstox_token", token=token)
        self.assertEqual(denied.status_code, 403)

    def test_llm_client_token_refused_for_near_miss_names(self):
        token = self._use_llm_client_token()
        for name in (
            "llm_keyx",
            "llm_key_",
            "llm_",
            "llm_key",
            "llm_key_openai-main",
            "llm_key_OpenAI",
            "llm_key_1openai",
            "llm_key_" + "x" * 42,
        ):
            with self.subTest(name=name):
                self.get_value.reset_mock()
                resp = self._get(name, token=token)
                self.assertEqual(resp.status_code, 403)
                self.get_value.assert_not_called()

    def test_collector_token_refused_for_llm_key_names(self):
        resp = self._get("llm_key_openai", token=self.TOKEN)
        self.assertEqual(resp.status_code, 403)
        self.get_value.assert_not_called()

    def test_wrong_llm_style_token_is_401_on_secrets(self):
        self._use_llm_client_token()
        resp = self._get("llm_key_openai", token="tok-matches-neither")
        self.assertEqual(resp.status_code, 401)
        self.get_value.assert_not_called()

    def test_llm_client_token_reads_llm_key_when_collector_file_missing(self):
        token = self._use_llm_client_token()
        missing = os.path.join(os.path.dirname(self.token_file), "does-not-exist")
        with patch.dict(os.environ, {"COLLECTOR_TOKEN_FILE": missing}):
            resp = self._get("llm_key_openai", token=token)
        self.assertTrue(200 <= resp.status_code < 300,
                        f"expected 2xx for llm_key_openai with collector file missing, got {resp.status_code}")


# ---------------------------------------------------------------------------
# B. Client: scanner/service_client.py
# ---------------------------------------------------------------------------

def _fake_response(body: bytes):
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _request_parts(call):
    """(url, Authorization header) from a urlopen call, whether it got a str or a Request."""
    arg = call.args[0]
    if isinstance(arg, urllib.request.Request):
        return arg.full_url, arg.get_header("Authorization")
    return arg, None


class FetchSecretClient(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.token_file = os.path.join(self.dir, "collector_token")
        with open(self.token_file, "w", encoding="utf-8") as f:
            f.write("tok-abc\n")

    def _fetch(self, **kwargs):
        from scanner.service_client import fetch_secret
        return fetch_secret("upstox_analytics_token", **kwargs)

    def _exc(self):
        from scanner.service_client import SecretUnavailable
        return SecretUnavailable

    def test_returns_value_and_sends_bearer_token(self):
        body = b'{"name":"upstox_analytics_token","value":"V1"}'
        with patch("urllib.request.urlopen", return_value=_fake_response(body)) as urlopen:
            value = self._fetch(token_file=self.token_file, base_url="http://ui:8080")
        self.assertEqual(value, "V1")
        url, auth = _request_parts(urlopen.call_args)
        self.assertEqual(url, "http://ui:8080/internal/secrets/upstox_analytics_token")
        self.assertEqual(auth, "Bearer tok-abc")

    def test_missing_token_file_raises_without_leaking_token(self):
        missing = os.path.join(self.dir, "absent")
        with patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(self._exc()) as ctx:
                self._fetch(token_file=missing, base_url="http://ui:8080")
        urlopen.assert_not_called()
        self.assertNotIn("tok-abc", str(ctx.exception))

    def test_http_401_raises_with_status_and_no_secret_text(self):
        err = urllib.error.HTTPError("http://ui:8080/internal/secrets/x", 401, "Unauthorized", {}, None)
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(self._exc()) as ctx:
                self._fetch(token_file=self.token_file, base_url="http://ui:8080")
        msg = str(ctx.exception)
        self.assertIn("401", msg)
        self.assertNotIn("tok-abc", msg)
        self.assertNotIn("SECRET-V9", msg)

    def test_connection_failure_raises_unreachable(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            with self.assertRaises(self._exc()) as ctx:
                self._fetch(token_file=self.token_file, base_url="http://ui:8080")
        self.assertIn("unreachable", str(ctx.exception).lower())

    def test_defaults_come_from_environment(self):
        body = b'{"name":"upstox_analytics_token","value":"V2"}'
        env = {"SECRETS_API_URL": "http://api.example.test:9", "SERVICE_TOKEN_FILE": self.token_file}
        with patch.dict(os.environ, env), \
                patch("urllib.request.urlopen", return_value=_fake_response(body)) as urlopen:
            value = self._fetch()
        self.assertEqual(value, "V2")
        url, _ = _request_parts(urlopen.call_args)
        self.assertEqual(url, "http://api.example.test:9/internal/secrets/upstox_analytics_token")


# ---------------------------------------------------------------------------
# C. Collector wiring: scanner/collect/sources.py takes the token from the service
# ---------------------------------------------------------------------------

def _one_symbol():
    import pandas as pd
    return pd.DataFrame({"Symbol": ["AAA"], "ISIN Code": ["INE000000001"]})


class CollectorUsesServiceToken(unittest.TestCase):
    def _run_candles(self, **extra_patches):
        from scanner.collect.sources import CandlesEOD
        ist = pytz.timezone("Asia/Kolkata")
        after_close = ist.localize(datetime(2024, 9, 30, 16, 30, 0)).astimezone(pytz.UTC)
        stack = [
            patch("scanner.constituents.load_constituents", return_value=_one_symbol()),
            patch("dotenv.load_dotenv"),
            patch("scanner.history.collect_eod",
                  return_value={"fetched": 1, "new": 1, "from": None, "to": None}),
            patch("scanner.upstox.UpstoxClient"),
        ]
        mocks = []
        for p in stack:
            mocks.append(p.start())
            self.addCleanup(p.stop)
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("UPSTOX_ANALYTICS_ACCESS_TOKEN", None)
        result = CandlesEOD().run({}, now=after_close)
        return result, mocks[-1]

    def test_token_comes_from_service_client_not_env(self):
        with patch("scanner.collect.service_client.fetch_secret", return_value="svc-token") as fetch:
            _, upstox_client = self._run_candles()
        fetch.assert_called_with("upstox_analytics_token")
        upstox_client.assert_called_once()
        self.assertEqual(upstox_client.call_args.args[0], "svc-token")

    def test_unavailable_token_skips_with_message(self):
        from scanner.collect.service_client import SecretUnavailable
        with patch("scanner.collect.service_client.fetch_secret",
                   side_effect=SecretUnavailable("service unreachable")):
            result, upstox_client = self._run_candles()
        self.assertIn("upstox token unavailable", result["message"])
        upstox_client.assert_not_called()


# ---------------------------------------------------------------------------
# D. First-run check: scanner/collect/first_run.py
# ---------------------------------------------------------------------------

class FirstRunTokenCheck(unittest.TestCase):
    def test_true_when_service_returns_secret(self):
        from scanner.collect import first_run
        with patch("scanner.collect.service_client.fetch_secret", return_value="svc-token") as fetch:
            self.assertTrue(first_run._details_present())
        fetch.assert_called_with("upstox_analytics_token")

    def test_false_when_secret_unavailable(self):
        from scanner.collect import first_run
        from scanner.collect.service_client import SecretUnavailable
        with patch("scanner.collect.service_client.fetch_secret",
                   side_effect=SecretUnavailable("service unreachable")):
            self.assertFalse(first_run._details_present())


# ---------------------------------------------------------------------------
# E. CLI: python -m scanner.secrets_cli service-token collector --out PATH
# ---------------------------------------------------------------------------

class ServiceTokenCli(unittest.TestCase):
    TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{43}$")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        db = patch("scanner.pg.db.connect")
        db.start()
        self.addCleanup(db.stop)

    def _main(self, argv):
        """Returns (return code, stdout). A SystemExit from argparse counts as its code."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                rc = secrets_cli.main(argv)
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 1
        return rc, out.getvalue()

    def test_writes_new_random_token_file(self):
        path = os.path.join(self.dir, "collector_token")
        rc, _ = self._main(["service-token", "collector", "--out", path])
        self.assertEqual(rc, 0)
        with open(path, encoding="utf-8") as f:
            content = f.read().rstrip("\n")
        self.assertEqual(len(content), 43)
        self.assertRegex(content, self.TOKEN_SHAPE)

    def test_output_has_path_and_written_but_never_the_token(self):
        path = os.path.join(self.dir, "collector_token")
        rc, out = self._main(["service-token", "collector", "--out", path])
        self.assertEqual(rc, 0)
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
        self.assertIn("written", out)
        self.assertIn(path, out)
        self.assertNotIn(token, out)

    def test_refuses_to_overwrite_existing_file(self):
        # Success on a fresh path first, so this test fails on the overwrite rule and not on a missing command.
        fresh = os.path.join(self.dir, "fresh_token")
        rc_fresh, _ = self._main(["service-token", "collector", "--out", fresh])
        self.assertEqual(rc_fresh, 0)

        existing = os.path.join(self.dir, "existing_token")
        with open(existing, "w", encoding="utf-8") as f:
            f.write("old-token\n")
        rc, _ = self._main(["service-token", "collector", "--out", existing])
        self.assertNotEqual(rc, 0)
        with open(existing, encoding="utf-8") as f:
            self.assertEqual(f.read(), "old-token\n")

    def test_only_collector_name_is_accepted(self):
        # Success with the valid name first, so this test fails on the name rule and not on a missing command.
        ok_path = os.path.join(self.dir, "ok_token")
        rc_ok, _ = self._main(["service-token", "collector", "--out", ok_path])
        self.assertEqual(rc_ok, 0)

        path = os.path.join(self.dir, "other_token")
        rc, _ = self._main(["service-token", "kite", "--out", path])
        self.assertNotEqual(rc, 0)
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
