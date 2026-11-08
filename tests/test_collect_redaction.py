"""Credentials in exception text must not reach collector run messages or the API."""
import unittest

from scanner.collect import sources
from ui.app import api


class CollectEachRedactionTests(unittest.TestCase):
    def test_fetch_error_with_mongo_uri_is_masked(self):
        def fake_fetch(symbol):
            raise Exception("connect failed: mongodb://u:s3cret@h:27017/db")

        fetched, new, message = sources._collect_each(["ABC"], fake_fetch)

        self.assertEqual((fetched, new), (0, 0))
        self.assertNotIn("s3cret", message)
        self.assertIn("***", message)
        self.assertIn("1 of 1 symbols failed", message)

    def test_fetch_error_with_postgres_uri_is_masked(self):
        def fake_fetch(symbol):
            raise Exception("could not connect: postgres://app:pw123@db:5432/x")

        _, _, message = sources._collect_each(["ABC"], fake_fetch)

        self.assertNotIn("pw123", message)
        self.assertIn("***", message)


class RunMessageMaskingTests(unittest.TestCase):
    def test_serialize_run_masks_message(self):
        row = {"source": "announcements",
               "message": "Cannot connect at mongodb://u:s3cret@h:27017/db"}

        out = api.serialize_run(row)

        self.assertNotIn("s3cret", out["message"])
        self.assertIn("<redacted-uri>", out["message"])
        self.assertEqual(out["source"], "announcements")

    def test_serialize_run_removes_uri_scheme_and_credentials(self):
        row = {"source": "announcements",
               "message": "failed: mongodb://u:s3cret@h:27017/db"}

        out = api.serialize_run(row)

        self.assertNotIn("mongodb://", out["message"])
        self.assertNotIn("s3cret", out["message"])

    def test_serialize_run_without_message_is_unchanged(self):
        row = {"source": "candles_eod", "message": None}

        self.assertEqual(api.serialize_run(row), {"source": "candles_eod", "message": None})


if __name__ == "__main__":
    unittest.main()
