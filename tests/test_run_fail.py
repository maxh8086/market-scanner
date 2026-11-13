"""LC5 tests: record_run.py --fail --reason writes a failed runs row with a reason,
and scanner.metrics warns at run start when RUN_ID is unset.

Mocks only: no Postgres, no network.
"""

import os
import unittest
import uuid
from unittest import mock


class TestRunFail(unittest.TestCase):
    def test_run_fail_writes_failed_row_with_reason(self):
        import record_run

        run_id = str(uuid.uuid4())
        argv = ["--run-id", run_id, "--date", "2026-11-13",
                "--fail", "--reason", "model_not_set"]

        with mock.patch("scanner.pg.db.available", return_value=True), \
                mock.patch("scanner.pg.migrate.apply"), \
                mock.patch("scanner.runs.finish_run") as finish:
            try:
                rc = record_run.main(argv)
            except SystemExit as exc:
                self.fail(f"record_run.main rejected --reason (exit {exc.code}); "
                          "the flag does not exist yet")

        self.assertEqual(rc, 0)
        finish.assert_called_once()
        args, kwargs = finish.call_args
        self.assertEqual(args[0], run_id)
        self.assertEqual(args[1], "failed")
        self.assertEqual(kwargs.get("notes"), "model_not_set",
                         f"runs row notes is {kwargs.get('notes')!r}, expected 'model_not_set'")


class TestRunStartRunIdWarning(unittest.TestCase):
    def test_run_start_warns_when_run_id_unset(self):
        from scanner import metrics

        with mock.patch.dict(os.environ):
            os.environ.pop("RUN_ID", None)
            with self.assertLogs("scanner.metrics", level="WARNING") as logs:
                metrics.warn_if_run_id_unset()

        self.assertTrue(any("RUN_ID" in line for line in logs.output), logs.output)


if __name__ == "__main__":
    unittest.main()
