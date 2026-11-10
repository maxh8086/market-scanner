"""Offline tests for scanner/expiry_alerts.py. No database and no Telegram calls."""
import datetime as dt
import unittest
from unittest import mock

from scanner import expiry_alerts as ea

EXPIRES = dt.date(2027, 5, 18)
KEY = b"\x00" * 32
BOT_TOKEN = "123456:SECRET-BOT-TOKEN-VALUE"


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConn:
    """Answers the two statement shapes expiry_alerts.py uses (token_alert_sent select and insert)."""

    def __init__(self):
        self.sent = set()
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if sql.lstrip().startswith("INSERT"):
            self.sent.add(tuple(params))
            return _Result(None)
        return _Result((1,) if tuple(params) in self.sent else None)


class _Post:
    """Stands in for requests.post. Records each call and returns the given status and body."""

    def __init__(self, status=200, body=None, raise_exc=None):
        self.calls = []
        self.status = status
        self.body = {"ok": True} if body is None else body
        self.raise_exc = raise_exc

    def __call__(self, url, json=None, timeout=None):
        self.calls.append(json)
        if self.raise_exc:
            raise self.raise_exc
        resp = mock.Mock(status_code=self.status)
        resp.json.return_value = self.body
        return resp


def _stub_secrets(has_token=True, has_telegram=True, expires_on=EXPIRES):
    meta = {"name": ea.SECRET_NAME, "expires_on": expires_on} if has_token else None

    def get_meta(conn, name):
        return meta

    def get_value(conn, key, name):
        if name == ea.BOT_TOKEN_NAME and has_telegram:
            return BOT_TOKEN
        if name == ea.CHAT_ID_NAME and has_telegram:
            return "-1001"
        raise ea.app_secrets.SecretNotFound(name)

    return mock.patch.multiple(ea.app_secrets, get_meta=get_meta, get_value=get_value,
                               SecretNotFound=ea.app_secrets.SecretNotFound)


class DueKindTests(unittest.TestCase):
    def test_windows(self):
        cases = {
            45: None, 31: None, 30: "d30", 8: "d30", 7: "d7", 5: "d7", 2: "d7",
            1: "d1", 0: "d0", -1: None,
        }
        for days, want in cases.items():
            with self.subTest(days=days):
                today = EXPIRES - dt.timedelta(days=days)
                self.assertEqual(ea.due_kind(EXPIRES, today), want)


class CheckExpiryTests(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConn()

    def test_sends_once_then_skips(self):
        today = EXPIRES - dt.timedelta(days=7)
        post = _Post()
        with _stub_secrets():
            first = ea.check_expiry(self.conn, KEY, today, post=post)
            second = ea.check_expiry(self.conn, KEY, today, post=post)
        self.assertEqual(first, {"status": "sent", "kind": "d7"})
        self.assertEqual(second, {"status": "already_sent", "kind": "d7"})
        self.assertEqual(len(post.calls), 1)

    def test_message_has_name_and_date_only(self):
        today = EXPIRES - dt.timedelta(days=1)
        post = _Post()
        with _stub_secrets():
            ea.check_expiry(self.conn, KEY, today, post=post)
        text = post.calls[0]["text"]
        self.assertIn(ea.SECRET_NAME, text)
        self.assertIn("2027-05-18", text)
        self.assertNotIn(BOT_TOKEN, text)
        self.assertNotIn("SECRET-BOT-TOKEN-VALUE", text)

    def test_not_configured_sends_nothing(self):
        post = _Post()
        with _stub_secrets(has_telegram=False):
            out = ea.check_expiry(self.conn, KEY, EXPIRES - dt.timedelta(days=7), post=post)
        self.assertEqual(out, {"status": "not_configured", "kind": "d7"})
        self.assertEqual(post.calls, [])
        self.assertEqual(self.conn.sent, set())

    def test_failed_send_is_not_recorded_and_retries(self):
        today = EXPIRES - dt.timedelta(days=30)
        with _stub_secrets():
            bad = ea.check_expiry(self.conn, KEY, today, post=_Post(status=500))
            self.assertEqual(bad["status"], "send_failed")
            self.assertEqual(self.conn.sent, set())
            good_post = _Post()
            good = ea.check_expiry(self.conn, KEY, today, post=good_post)
        self.assertEqual(good, {"status": "sent", "kind": "d30"})
        self.assertEqual(len(good_post.calls), 1)

    def test_no_token_and_not_due(self):
        with _stub_secrets(has_token=False):
            self.assertEqual(ea.check_expiry(self.conn, KEY, EXPIRES, post=_Post()),
                             {"status": "no_token"})
        with _stub_secrets():
            self.assertEqual(ea.check_expiry(self.conn, KEY, EXPIRES - dt.timedelta(days=90),
                                             post=_Post()), {"status": "not_due"})


class AuthFailureTests(unittest.TestCase):
    def test_401_sends_once_per_expiry(self):
        conn = FakeConn()
        post = _Post()
        today = EXPIRES - dt.timedelta(days=100)
        with _stub_secrets():
            first = ea.alert_auth_failure(conn, KEY, today, 401, post=post)
            second = ea.alert_auth_failure(conn, KEY, today, 403, post=post)
        self.assertEqual(first, {"status": "sent", "kind": "auth"})
        self.assertEqual(second, {"status": "already_sent", "kind": "auth"})
        self.assertEqual(len(post.calls), 1)
        self.assertNotIn(BOT_TOKEN, post.calls[0]["text"])

    def test_other_status_is_ignored(self):
        with _stub_secrets():
            out = ea.alert_auth_failure(FakeConn(), KEY, EXPIRES, 500, post=_Post())
        self.assertEqual(out, {"status": "not_an_auth_error"})


class SendTelegramTests(unittest.TestCase):
    def test_exception_text_with_url_is_not_leaked(self):
        boom = RuntimeError(f"connection to https://api.telegram.org/bot{BOT_TOKEN}/sendMessage failed")
        with self.assertRaises(ea.AlertSendError) as ctx:
            ea.send_telegram(BOT_TOKEN, "-1", "hi", post=_Post(raise_exc=boom))
        self.assertNotIn(BOT_TOKEN, str(ctx.exception))

    def test_ok_false_is_a_failure(self):
        with self.assertRaises(ea.AlertSendError):
            ea.send_telegram(BOT_TOKEN, "-1", "hi", post=_Post(body={"ok": False}))

    def test_success(self):
        post = _Post()
        ea.send_telegram(BOT_TOKEN, "-1", "hi", post=post)
        self.assertEqual(post.calls, [{"chat_id": "-1", "text": "hi"}])


if __name__ == "__main__":
    unittest.main()
