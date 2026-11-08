"""Offline tests for the first-run watcher: the trigger decision, the marker, and one-time queueing."""
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pytz

from scanner.collect import first_run

NOW = datetime(2026, 11, 8, 10, 0, 0, tzinfo=pytz.UTC)


class DecideTests(unittest.TestCase):
    """Pure decision table."""

    def test_details_missing_waits(self):
        action, _ = first_run.decide(details_present=False, marker_present=False, run_in_progress=False)
        self.assertEqual(action, "wait")

    def test_details_present_no_marker_queues(self):
        action, _ = first_run.decide(details_present=True, marker_present=False, run_in_progress=False)
        self.assertEqual(action, "queue")

    def test_marker_present_is_done(self):
        action, _ = first_run.decide(details_present=True, marker_present=True, run_in_progress=False)
        self.assertEqual(action, "done")

    def test_marker_present_wins_over_missing_details(self):
        action, _ = first_run.decide(details_present=False, marker_present=True, run_in_progress=False)
        self.assertEqual(action, "done")

    def test_run_in_progress_does_not_queue(self):
        action, _ = first_run.decide(details_present=True, marker_present=False, run_in_progress=True)
        self.assertEqual(action, "mark")


class TickTests(unittest.TestCase):
    """tick() with injected fakes and a temp marker path. No Postgres, no Upstox."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.marker = self.tmp / "first_run_done"
        self.logs: list[str] = []
        self.queue_calls = 0
        self.queued_result = True

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _queue(self):
        self.queue_calls += 1
        return self.queued_result

    def _tick(self, details=True, running=False, queue=None):
        return first_run.tick(
            NOW, path=self.marker,
            details_present=lambda: details,
            run_in_progress=lambda: running,
            queue_run=queue or self._queue,
            log=self.logs.append,
        )

    def test_details_missing_does_not_queue_or_mark(self):
        self.assertEqual(self._tick(details=False), "wait")
        self.assertEqual(self.queue_calls, 0)
        self.assertFalse(self.marker.exists())
        self.assertIn("waiting for broker API details", self.logs[-1])

    def test_details_present_queues_once_and_writes_marker(self):
        self.assertEqual(self._tick(), "queue")
        self.assertEqual(self.queue_calls, 1)
        self.assertTrue(self.marker.is_file())
        self.assertIn("queued ath_scan", self.logs[-1])

    def test_second_pass_after_trigger_does_nothing(self):
        self._tick()
        self.assertEqual(self._tick(), "done")
        self.assertEqual(self.queue_calls, 1)

    def test_marker_present_skips_even_when_run_check_would_fail(self):
        self.marker.write_text("{}", encoding="utf-8")

        def boom():
            raise AssertionError("run check must not run once the marker exists")

        self.assertEqual(
            first_run.tick(NOW, path=self.marker, details_present=lambda: True,
                           run_in_progress=boom, queue_run=self._queue, log=self.logs.append),
            "done")
        self.assertEqual(self.queue_calls, 0)

    def test_run_in_progress_marks_without_queueing(self):
        self.assertEqual(self._tick(running=True), "mark")
        self.assertEqual(self.queue_calls, 0)
        self.assertTrue(self.marker.is_file())
        self.assertIn("already in progress", self.logs[-1])

    def test_queue_failure_writes_no_marker_and_retries(self):
        def fail():
            raise ValueError("unknown source: ath_scan")

        self.assertEqual(self._tick(queue=fail), "error")
        self.assertFalse(self.marker.exists())
        # Next pass retries and succeeds once the source exists.
        self.assertEqual(self._tick(), "queue")
        self.assertEqual(self.queue_calls, 1)

    def test_already_pending_request_still_counts_as_triggered(self):
        self.queued_result = False  # request_run: one request already pending
        self.assertEqual(self._tick(), "queue")
        self.assertTrue(self.marker.is_file())
        self.assertIn("queued=False", self.logs[-1])

    def test_run_check_error_writes_no_marker(self):
        def db_down():
            raise RuntimeError("Postgres unreachable")

        self.assertEqual(
            first_run.tick(NOW, path=self.marker, details_present=lambda: True,
                           run_in_progress=db_down, queue_run=self._queue, log=self.logs.append),
            "error")
        self.assertEqual(self.queue_calls, 0)
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
