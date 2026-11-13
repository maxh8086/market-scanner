"""Offline tests for GET /internal/llm/providers/{provider_id} (LC2).

Covers the llm-client bearer token on the provider endpoint, the six-field response
shape, and the 401, 403 and 404 cases. Each service token is matched on its own, so the
llm-client token must work even when the collector token file is missing. No database:
scanner.pg.db.connect is patched. No network.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

COLLECTOR_TOKEN = "tok-collector-123"
LLM_TOKEN = "tok-llm-client-456"
PROVIDER_ID = "prov-openai-1"
ROW = {
    "provider_id": PROVIDER_ID,
    "class": "llm",
    "origin": "https://api.example.test",
    "approved": True,
    "key_ref": "llm_key_openai",
    "key_version": 3,
    "key_value": "SHOULD-NOT-LEAK",
}


class LlmProviderEndpoint(unittest.TestCase):
    def _patch(self, target, **kwargs):
        p = patch(target, **kwargs)
        mock = p.start()
        self.addCleanup(p.stop)
        return mock

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.collector_file = os.path.join(self.dir, "collector_token")
        self.llm_file = os.path.join(self.dir, "llm_client_token")
        self.missing = os.path.join(self.dir, "does-not-exist")
        with open(self.collector_file, "w", encoding="utf-8") as f:
            f.write(COLLECTOR_TOKEN)
        with open(self.llm_file, "w", encoding="utf-8") as f:
            f.write(LLM_TOKEN)

        env = patch.dict(os.environ, {"COLLECTOR_TOKEN_FILE": self.collector_file,
                                      "LLM_CLIENT_TOKEN_FILE": self.llm_file})
        env.start()
        self.addCleanup(env.stop)

        self.db_connect = self._patch("scanner.pg.db.connect")
        self.conn = self.db_connect.return_value.__enter__.return_value
        self.conn.execute.return_value.fetchone.return_value = dict(ROW)

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from ui.app import internal_secrets

        app = FastAPI()
        app.include_router(internal_secrets.router)
        return TestClient(app)

    def _get(self, token=COLLECTOR_TOKEN, provider_id=PROVIDER_ID):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        return self._client().get(f"/internal/llm/providers/{provider_id}", headers=headers)

    def test_llm_token_works_when_collector_token_file_missing(self):
        with patch.dict(os.environ, {"COLLECTOR_TOKEN_FILE": self.missing}):
            resp = self._get(token=LLM_TOKEN)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["provider_id"], PROVIDER_ID)

    def test_provider_200_returns_six_fields_only(self):
        resp = self._get(token=LLM_TOKEN)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(set(body.keys()),
                         {"provider_id", "class", "origin", "approved", "key_ref", "key_version"})
        self.assertNotIn("SHOULD-NOT-LEAK", resp.text)
        self.assertIn("no-store", resp.headers.get("Cache-Control", "").lower())

    def test_provider_collector_token_403(self):
        resp = self._get(token=COLLECTOR_TOKEN)
        self.assertEqual(resp.status_code, 403)
        self.conn.execute.assert_not_called()

    def test_provider_no_token_401(self):
        resp = self._get(token=None)
        self.assertEqual(resp.status_code, 401)
        self.conn.execute.assert_not_called()

    def test_provider_missing_row_404(self):
        self.conn.execute.return_value.fetchone.return_value = None
        resp = self._get(token=LLM_TOKEN)
        self.assertEqual(resp.status_code, 404)

    def test_provider_wrong_token_401(self):
        resp = self._get(token="tok-matches-neither")
        self.assertEqual(resp.status_code, 401)
        self.conn.execute.assert_not_called()

    def test_provider_503_when_both_token_files_missing(self):
        with patch.dict(os.environ, {"COLLECTOR_TOKEN_FILE": self.missing,
                                     "LLM_CLIENT_TOKEN_FILE": self.missing}):
            resp = self._get(token=LLM_TOKEN)
        self.assertEqual(resp.status_code, 503)
        self.conn.execute.assert_not_called()

    def test_unauthenticated_path_cannot_forge_log_lines(self):
        injected = "FAKE-LOG-LINE-DO-NOT-TRUST"
        provider_id = f"x%0A{injected}"
        with self.assertLogs(level="INFO") as logs:
            resp = self._get(token="tok-matches-neither", provider_id=provider_id)
        self.assertEqual(resp.status_code, 401)
        self.conn.execute.assert_not_called()
        messages = [record.getMessage() for record in logs.records]
        self.assertTrue(messages)
        for msg in messages:
            self.assertNotIn("\n", msg)
            self.assertNotIn("\r", msg)
            self.assertNotIn("\n" + injected, msg)
        self.assertTrue(any("x?" + injected in msg for msg in messages))


if __name__ == "__main__":
    unittest.main()
