"""Offline unit tests for scanner/broker_tokens.py (broker login, phase 1).

Pure functions only: fixed datetimes, no database, no network.
"""
import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from scanner import app_secrets, broker_tokens

IST = ZoneInfo("Asia/Kolkata")
UTC = dt.timezone.utc


def ist(*args):
    return dt.datetime(*args, tzinfo=IST)


class SecretNames(unittest.TestCase):
    def test_builds_per_profile_per_broker_names(self):
        self.assertEqual(broker_tokens.secret_name("default", "kite", "access_token"),
                         "broker_default_kite_access_token")
        self.assertEqual(broker_tokens.secret_name("work2", "kite", "api_key"),
                         "broker_work2_kite_api_key")
        self.assertEqual(broker_tokens.secret_name("work", "upstox", "api_secret"),
                         "broker_work_upstox_api_secret")

    def test_rejects_bad_profile_broker_and_kind(self):
        bad_profiles = ("", "Default", "work_2", "1abc", "a" * 17, "dflt.x", "a b")
        for profile in bad_profiles:
            with self.subTest(profile=profile):
                with self.assertRaises(ValueError):
                    broker_tokens.secret_name(profile, "kite", "access_token")
        with self.assertRaises(ValueError):
            broker_tokens.secret_name("default", "zerodha", "access_token")
        with self.assertRaises(ValueError):
            broker_tokens.secret_name("default", "kite", "request_token")

    def test_regex_accepts_only_the_documented_shape(self):
        self.assertIsNotNone(broker_tokens.SECRET_NAME_RE.match("broker_default_kite_access_token"))
        self.assertIsNotNone(broker_tokens.SECRET_NAME_RE.match("broker_a_upstox_api_key"))
        for name in ("broker_default_kite_access_token.bak", "kite_api_key",
                     "broker_default_zerodha_api_key", "broker_default_kite_refresh_token",
                     "broker_Default_kite_api_key", "broker__kite_api_key"):
            with self.subTest(name=name):
                self.assertIsNone(broker_tokens.SECRET_NAME_RE.match(name))

    def test_longest_names_fit_app_secret_name_rule(self):
        for kind in broker_tokens.KINDS:
            name = broker_tokens.secret_name("a" + "z" * 15, "upstox", kind)
            with self.subTest(name=name):
                self.assertEqual(app_secrets.validate_name(name), name)

    def test_parse_returns_parts_or_none(self):
        self.assertEqual(broker_tokens.parse_secret_name("broker_work_kite_api_secret"),
                         ("work", "kite", "api_secret"))
        self.assertIsNone(broker_tokens.parse_secret_name("kite_api_key"))
        self.assertIsNone(broker_tokens.parse_secret_name(None))


class TokenExpiry(unittest.TestCase):
    def test_before_cutoff_expires_same_morning(self):
        # 05:30 IST on 14 Nov -> 06:00 IST on 14 Nov, which is 00:30 UTC.
        expiry = broker_tokens.token_expiry("kite", ist(2026, 11, 14, 5, 30))
        self.assertEqual(expiry, dt.datetime(2026, 11, 14, 0, 30, tzinfo=UTC))

    def test_after_cutoff_expires_next_morning(self):
        # 10:00 IST on 14 Nov -> 06:00 IST on 15 Nov.
        expiry = broker_tokens.token_expiry("kite", ist(2026, 11, 14, 10, 0))
        self.assertEqual(expiry, dt.datetime(2026, 11, 15, 0, 30, tzinfo=UTC))

    def test_exactly_at_cutoff_expires_next_day(self):
        # The cut-off is strictly after issue time, so 06:00:00 IST gives the following day.
        expiry = broker_tokens.token_expiry("kite", ist(2026, 11, 14, 6, 0, 0))
        self.assertEqual(expiry, dt.datetime(2026, 11, 15, 0, 30, tzinfo=UTC))

    def test_result_is_utc_aware(self):
        expiry = broker_tokens.token_expiry("kite", ist(2026, 11, 14, 5, 0))
        self.assertIsNotNone(expiry.utcoffset())
        self.assertEqual(expiry.utcoffset(), dt.timedelta(0))

    def test_utc_input_is_converted_to_ist_before_the_cutoff_check(self):
        # 00:45 UTC is 06:15 IST, so the next cut-off is the following morning.
        issued = dt.datetime(2026, 11, 14, 0, 45, tzinfo=UTC)
        self.assertEqual(broker_tokens.token_expiry("kite", issued),
                         dt.datetime(2026, 11, 15, 0, 30, tzinfo=UTC))

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            broker_tokens.token_expiry("kite", dt.datetime(2026, 11, 14, 5, 30))
        with self.assertRaises(ValueError):
            broker_tokens.is_expired("kite", ist(2026, 11, 14, 5, 30),
                                     dt.datetime(2026, 11, 14, 6, 0))

    def test_unknown_broker_is_rejected(self):
        with self.assertRaises(ValueError):
            broker_tokens.token_expiry("zerodha", ist(2026, 11, 14, 5, 30))

    def test_upstox_cutoff_is_0330(self):
        # 10:00 IST on 14 Nov -> 03:30 IST on 15 Nov, which is 22:00 UTC on 14 Nov.
        expiry = broker_tokens.token_expiry("upstox", ist(2026, 11, 14, 10, 0))
        self.assertEqual(expiry, dt.datetime(2026, 11, 14, 22, 0, tzinfo=UTC))


class IsExpired(unittest.TestCase):
    ISSUED = ist(2026, 11, 14, 10, 0)  # expires 15 Nov 06:00 IST (15 Nov 00:30 UTC)

    def test_before_expiry_is_not_expired(self):
        now = dt.datetime(2026, 11, 15, 0, 29, 59, tzinfo=UTC)
        self.assertFalse(broker_tokens.is_expired("kite", self.ISSUED, now))

    def test_at_expiry_is_expired(self):
        now = dt.datetime(2026, 11, 15, 0, 30, tzinfo=UTC)
        self.assertTrue(broker_tokens.is_expired("kite", self.ISSUED, now))

    def test_after_expiry_is_expired(self):
        now = dt.datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
        self.assertTrue(broker_tokens.is_expired("kite", self.ISSUED, now))


if __name__ == "__main__":
    unittest.main()
