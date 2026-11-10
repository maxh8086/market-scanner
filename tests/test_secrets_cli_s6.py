"""Offline tests for S6: live checks, `secrets_cli test` and `secrets_cli rotate`. No network, no DB."""
import datetime as dt
import os
import unittest
from unittest import mock

from scanner import app_secrets as s
from scanner import secret_checks as sc
from scanner import secrets_cli as cli
from tests.test_secrets_cli import Conn

KEY = os.urandom(32)
TODAY = dt.date(2026, 11, 10)
TG_TOKEN = "123456:FAKE-telegram-token-ZZ99"
UP_TOKEN = "fake-upstox-token-QQ77"


class Resp:
    def __init__(self, status, body=None, json_exc=None):
        self.status_code = status
        self._body = body
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._body


class FakeGet:
    """Records every call. Returns `resp`, or raises `exc` if given."""

    def __init__(self, resp=None, exc=None):
        self.resp = resp
        self.exc = exc
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.resp


class TelegramCheck(unittest.TestCase):
    def test_passes_on_200_ok_true_and_only_calls_getme(self):
        get = FakeGet(Resp(200, {"ok": True, "result": {"id": 1}}))
        self.assertIsNone(sc.check_telegram_token(TG_TOKEN, get=get))
        self.assertEqual(len(get.calls), 1)
        url, kwargs = get.calls[0]
        self.assertEqual(url, f"https://api.telegram.org/bot{TG_TOKEN}/getMe")
        self.assertEqual(kwargs.get("timeout"), 15)
        for u, _ in get.calls:
            self.assertNotIn("sendMessage", u)

    def test_fails_when_ok_false_and_message_has_no_token(self):
        get = FakeGet(Resp(200, {"ok": False, "description": "x"}))
        with self.assertRaises(sc.SecretCheckFailed) as ctx:
            sc.check_telegram_token(TG_TOKEN, get=get)
        self.assertEqual(str(ctx.exception), "telegram getMe rejected (HTTP 200)")
        self.assertNotIn(TG_TOKEN, str(ctx.exception))

    def test_fails_on_non_200_with_code(self):
        get = FakeGet(Resp(401, {"ok": False}))
        with self.assertRaises(sc.SecretCheckFailed) as ctx:
            sc.check_telegram_token(TG_TOKEN, get=get)
        self.assertEqual(str(ctx.exception), "telegram getMe rejected (HTTP 401)")

    def test_non_json_body_counts_as_rejected(self):
        get = FakeGet(Resp(200, json_exc=ValueError("not json")))
        with self.assertRaises(sc.SecretCheckFailed):
            sc.check_telegram_token(TG_TOKEN, get=get)


class UpstoxCheck(unittest.TestCase):
    def test_passes_on_200_with_bearer_header_and_quote_endpoint(self):
        get = FakeGet(Resp(200, {"data": {}}))
        self.assertIsNone(sc.check_upstox_token(UP_TOKEN, get=get))
        url, kwargs = get.calls[0]
        self.assertTrue(url.endswith("/v3/market-quote/ohlc"))
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {UP_TOKEN}")
        self.assertEqual(kwargs["headers"]["Accept"], "application/json")
        self.assertEqual(kwargs["params"]["instrument_key"], sc.UPSTOX_PROBE_KEY)
        self.assertEqual(kwargs["timeout"], 15)
        self.assertEqual(len(get.calls), 1)

    def test_401_and_403_are_rejections_without_token(self):
        for code in (401, 403):
            with self.subTest(code=code):
                get = FakeGet(Resp(code))
                with self.assertRaises(sc.SecretCheckFailed) as ctx:
                    sc.check_upstox_token(UP_TOKEN, get=get)
                self.assertEqual(str(ctx.exception), f"upstox rejected the token (HTTP {code})")
                self.assertNotIn(UP_TOKEN, str(ctx.exception))

    def test_other_status_reports_code(self):
        get = FakeGet(Resp(500))
        with self.assertRaises(sc.SecretCheckFailed) as ctx:
            sc.check_upstox_token(UP_TOKEN, get=get)
        self.assertEqual(str(ctx.exception), "upstox returned HTTP 500")


class NoLeakage(unittest.TestCase):
    def test_telegram_exception_text_with_url_and_token_is_not_leaked(self):
        url = f"https://api.telegram.org/bot{TG_TOKEN}/getMe"
        get = FakeGet(exc=RuntimeError(f"connection refused for {url} body={TG_TOKEN}"))
        with self.assertRaises(sc.SecretCheckFailed) as ctx:
            sc.check_telegram_token(TG_TOKEN, get=get)
        self.assertEqual(str(ctx.exception), "telegram request failed")
        self.assertNotIn(TG_TOKEN, str(ctx.exception))
        self.assertNotIn("api.telegram.org", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)

    def test_upstox_exception_text_with_token_is_not_leaked(self):
        get = FakeGet(exc=RuntimeError(f"Authorization: Bearer {UP_TOKEN} to {sc.BASE_URL}"))
        with self.assertRaises(sc.SecretCheckFailed) as ctx:
            sc.check_upstox_token(UP_TOKEN, get=get)
        self.assertEqual(str(ctx.exception), "upstox request failed")
        self.assertNotIn(UP_TOKEN, str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)


def _ok(value):
    return None


def _bad(value):
    raise sc.SecretCheckFailed("test failure text")


class CmdTest(unittest.TestCase):
    NAME = "telegram_bot_token"

    def setUp(self):
        self.conn = Conn()
        s.put(self.conn, KEY, self.NAME, "stored-token-1234", created_on=TODAY,
              expires_on=None, updated_by="admin")
        self.lines = []

    def run_cmd(self, checks):
        return cli.cmd_test(self.conn, KEY, self.NAME, checks, self.lines.append)

    def test_pass_returns_0_and_never_puts(self):
        check = mock.Mock(side_effect=_ok)
        with mock.patch.object(cli.app_secrets, "put") as put:
            code = self.run_cmd({self.NAME: check})
        self.assertEqual(code, 0)
        check.assert_called_once_with("stored-token-1234")
        put.assert_not_called()
        self.assertIn(f"test passed: {self.NAME}", self.lines)

    def test_fail_returns_1_and_never_puts(self):
        with mock.patch.object(cli.app_secrets, "put") as put:
            code = self.run_cmd({self.NAME: _bad})
        self.assertEqual(code, 1)
        put.assert_not_called()
        self.assertIn("test failed: test failure text", self.lines)
        self.assertNotIn("stored-token-1234", "\n".join(self.lines))

    def test_name_without_check_returns_2(self):
        self.assertEqual(self.run_cmd({}), 2)

    def test_missing_stored_name_returns_1(self):
        code = cli.cmd_test(self.conn, KEY, "upstox_analytics_token", {"upstox_analytics_token": _ok},
                            self.lines.append)
        self.assertEqual(code, 1)
        self.assertIn("not found: upstox_analytics_token", self.lines)


class CmdRotate(unittest.TestCase):
    NAME = "telegram_bot_token"
    NEW = "new-token-9876"

    def setUp(self):
        self.conn = Conn()
        self.lines = []

    def run_cmd(self, checks, read=lambda: CmdRotate.NEW):
        return cli.cmd_rotate(self.conn, KEY, self.NAME, TODAY, None, "admin", read, checks,
                              self.lines.append)

    def test_pass_puts_once_with_candidate_and_returns_0(self):
        with mock.patch.object(cli.app_secrets, "put", wraps=s.put) as put:
            code = self.run_cmd({self.NAME: _ok})
        self.assertEqual(code, 0)
        put.assert_called_once()
        self.assertEqual(put.call_args.args[3], self.NEW)
        self.assertEqual(s.get_value(self.conn, KEY, self.NAME), self.NEW)
        self.assertNotIn(self.NEW, "\n".join(self.lines))
        self.assertIn(f"rotated {self.NAME} (...9876)", "\n".join(self.lines))

    def test_fail_does_not_put_and_returns_1(self):
        with mock.patch.object(cli.app_secrets, "put") as put:
            code = self.run_cmd({self.NAME: _bad})
        self.assertEqual(code, 1)
        put.assert_not_called()
        self.assertEqual(self.conn.rows, {})
        self.assertIn("not saved: test failed: test failure text", self.lines)

    def test_read_back_mismatch_returns_1(self):
        with mock.patch.object(cli.app_secrets, "get_value", return_value="something-else"):
            code = self.run_cmd({self.NAME: _ok})
        self.assertEqual(code, 1)
        self.assertIn("stored, but the read-back check failed; check the master key", self.lines)

    def test_name_without_check_returns_2_before_reading_value(self):
        read = mock.Mock(return_value=self.NEW)
        code = self.run_cmd({}, read=read)
        self.assertEqual(code, 2)
        read.assert_not_called()

    def test_main_rotate_commits_on_pass_and_rolls_back_on_fail(self):
        conn = Conn()
        code = cli.main(["rotate", self.NAME, "--created", "2026-11-10", "--expires", "none"],
                        conn_factory=lambda: conn, key_loader=lambda: KEY,
                        read_value=lambda: self.NEW, checks={self.NAME: _ok},
                        today=TODAY, out=lambda _: None)
        self.assertEqual(code, 0)
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))
        conn2 = Conn()
        code = cli.main(["rotate", self.NAME, "--created", "2026-11-10", "--expires", "2027-11-10"],
                        conn_factory=lambda: conn2, key_loader=lambda: KEY,
                        read_value=lambda: self.NEW, checks={self.NAME: _bad},
                        today=TODAY, out=lambda _: None)
        self.assertEqual(code, 1)
        self.assertEqual(conn2.rows, {})
        self.assertEqual((conn2.commits, conn2.rollbacks), (0, 1))


class MainArgs(unittest.TestCase):
    def test_rotate_without_expires_is_argparse_error(self):
        with self.assertRaises(SystemExit):
            cli.main(["rotate", "telegram_bot_token", "--created", "2026-11-10"],
                     conn_factory=Conn, key_loader=lambda: KEY,
                     read_value=lambda: "x", checks={}, out=lambda _: None)

    def test_test_unknown_name_returns_2(self):
        lines = []
        code = cli.main(["test", "unknown_name"], conn_factory=Conn, key_loader=lambda: KEY,
                        checks={}, out=lines.append)
        self.assertEqual(code, 2)
        self.assertIn("no test for unknown_name", lines)


if __name__ == "__main__":
    unittest.main()
