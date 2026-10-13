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


if __name__ == "__main__":
    unittest.main()
