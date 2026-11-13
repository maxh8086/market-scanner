"""LC5 tests: llm-client /healthz fields, the scanner health probe, and one llm_calls
record per cloud call (migration 055 adds the provider columns).

Mocks only: no Postgres, no network. Until LC5 lands these fail on the missing
healthz fields, the non-healthz probe path, and the missing provider columns.
"""

import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_055 = REPO_ROOT / "db" / "migrations" / "055_llm_calls_provider.sql"

CHAT_TOKEN = "test-chat-token-healthz"
KEY_VALUE = "sk-test-not-real-healthz"
PROVIDER_ID = "openai_main"
KEY_REF = "llm_key_openai_main"
ORIGIN = "https://api.openai.com/v1/"

# M-18 fields: active provider id, class, route, base host, model set, key resolved,
# secrets API reachable, time of last successful call.
HEALTHZ_FIELDS = (
    "provider_id",
    "class",
    "route",
    "base_host",
    "model_set",
    "key_resolved",
    "secrets_reachable",
    "last_success_at",
)


class FakeUi:
    """Stands in for the UI-side registry that llm-client reads provider and key rows from."""

    def get_active_provider_id(self):
        return PROVIDER_ID

    def get_provider(self, provider_id):
        if provider_id != PROVIDER_ID:
            return None
        return {
            "provider_id": PROVIDER_ID,
            "class": "openai_compat",
            "origin": ORIGIN,
            "approved": True,
            "key_ref": KEY_REF,
            "key_version": 1,
        }

    def get_key(self, key_ref):
        if key_ref != KEY_REF:
            return None
        return {"value": KEY_VALUE, "key_version": 1, "origin": ORIGIN}


class TestHealthz(unittest.TestCase):
    def test_healthz_fields(self):
        from fastapi.testclient import TestClient

        from llm_client.app import create_app

        app = create_app(chat_token=CHAT_TOKEN, ui=FakeUi())
        resp = TestClient(app).get("/healthz")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        missing = [f for f in HEALTHZ_FIELDS if f not in body]
        self.assertEqual(missing, [], f"/healthz is missing M-18 fields: {missing}")
        self.assertEqual(body["class"], "openai_compat")
        self.assertEqual(body["base_host"], "api.openai.com")
        # Host only: no key, no full origin URL, no path or query.
        self.assertNotIn(KEY_VALUE, resp.text)
        self.assertNotIn("https://", resp.text)
        self.assertNotIn("/v1", resp.text)


class TestHealthProbe(unittest.TestCase):
    def test_health_probes_healthz_only(self):
        from scanner import llm

        cfg = llm.LLMConfig(base_url="http://llm-client:8080", api="openai")
        probe_resp = mock.MagicMock(status_code=200)
        probe_resp.json.return_value = {"status": "ok"}

        with mock.patch("requests.get", return_value=probe_resp) as get:
            ok, _detail = llm.health(cfg)

        self.assertTrue(ok)
        self.assertEqual(get.call_count, 1, "health() should make exactly one request")
        args, kwargs = get.call_args
        url = args[0] if args else kwargs["url"]
        self.assertEqual(url, "http://llm-client:8080/healthz", f"health() probed {url}")


class TestOneCloudCallOneRecord(unittest.TestCase):
    def test_one_cloud_call_writes_one_record(self):
        from scanner import llm

        run_id = str(uuid.uuid4())
        cfg = llm.LLMConfig(base_url="https://api.openai.com", model="gpt-test", api="openai")
        post_resp = mock.MagicMock(status_code=200, text="")
        post_resp.json.return_value = {
            "content": '{"order_amount": 1, "order_unit": "crore"}',
        }
        cursor = mock.MagicMock()
        cursor.__enter__.return_value = cursor
        conn = mock.MagicMock()
        conn.cursor.return_value = cursor

        with mock.patch.dict(os.environ, {"RUN_ID": run_id}), \
                mock.patch("scanner.llm._chat_token", return_value="test-token"), \
                mock.patch("requests.post", return_value=post_resp) as post, \
                mock.patch("scanner.metrics._get_connection", return_value=conn):
            result = llm.extract(cfg, "Broad consideration: Rs. 1 crore",
                                 kind=llm.KIND_ORDER, source_key="seq-1", symbol="ABC")

        self.assertTrue(result.ok)
        self.assertEqual(post.call_count, 1)
        inserts = [c for c in cursor.execute.call_args_list
                   if "INSERT INTO llm_calls" in c.args[0]]
        self.assertEqual(len(inserts), 1, "one cloud call must write exactly one llm_calls row")
        sql = inserts[0].args[0]
        for column in ("provider_id", "route", "base_host"):
            self.assertIn(column, sql, f"llm_calls insert has no {column} column")
        self.assertTrue(MIGRATION_055.exists(), f"missing {MIGRATION_055.name}")


if __name__ == "__main__":
    unittest.main()
