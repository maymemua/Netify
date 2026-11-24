import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from server import main


class StartupWithoutNeo4jTest(unittest.TestCase):
    def setUp(self):
        main.app.state.db = None

    def test_app_starts_and_reports_missing_config(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("NEO4J_") and k != "VNSHOP_PASSWORD"}
        with mock.patch.dict(os.environ, env, clear=True):
            with TestClient(main.app) as client:  # chạy cả lifespan: không được sập
                health = client.get("/healthz").json()
                self.assertEqual(health, {"ok": True, "web_files": True,
                                          "neo4j_configured": False, "password_set": False})
                self.assertEqual(client.get("/").status_code, 200)
                r = client.get("/api/info")
                self.assertEqual(r.status_code, 503)
                self.assertIn("Không kết nối được Neo4j", r.json()["detail"])
                self.assertIn("NEO4J_URI", r.json()["detail"])


class ConnectRetryTest(unittest.IsolatedAsyncioTestCase):
    def _fake_db(self, failures):
        calls = {"n": 0, "closed": 0}

        class Fake:
            async def init_schema(self):
                calls["n"] += 1
                if calls["n"] <= len(failures):
                    raise failures[calls["n"] - 1]

            async def close(self):
                calls["closed"] += 1

        return Fake, calls

    async def test_retries_transient_dns_error_then_succeeds(self):
        dns = ValueError("Failed to DNS resolve address x:7687: [Errno 16] Device or resource busy")
        fake, calls = self._fake_db([dns, dns])
        with mock.patch.object(main, "GraphDB", fake), mock.patch.object(main.asyncio, "sleep", mock.AsyncMock()):
            await main._connect_with_retry()
        self.assertEqual(calls["n"], 3)
        self.assertEqual(calls["closed"], 2)  # kết nối hỏng được đóng, không để rò

    async def test_does_not_retry_wrong_password(self):
        fake, calls = self._fake_db([RuntimeError("AuthError: The client is unauthorized")] * 3)
        with mock.patch.object(main, "GraphDB", fake), mock.patch.object(main.asyncio, "sleep", mock.AsyncMock()):
            with self.assertRaises(RuntimeError):
                await main._connect_with_retry()
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
