import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from server import auth
from server.main import app


class AuthTest(unittest.TestCase):
    def setUp(self):
        auth._failures.clear()
        # Không dùng "with TestClient": bỏ qua lifespan nên không cần Neo4j.
        self.client = TestClient(app, base_url="https://testserver")

    def env(self, **values):
        return mock.patch.dict(os.environ, values)

    def test_no_password_means_open(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VNSHOP_PASSWORD", None)
            r = self.client.get("/login", follow_redirects=False)
            self.assertEqual(r.status_code, 303)
            self.assertEqual(r.headers["location"], "/")

    def test_requires_login_when_password_set(self):
        with self.env(VNSHOP_PASSWORD="bí-mật"):
            r = self.client.get("/", follow_redirects=False)
            self.assertEqual((r.status_code, r.headers["location"]), (303, "/login"))
            self.assertEqual(self.client.get("/api/search?q=x").status_code, 401)
            self.assertEqual(self.client.get("/static/app.js", follow_redirects=False).status_code, 303)
            self.assertTrue(self.client.get("/healthz").json()["ok"])  # /healthz không cần đăng nhập
            self.assertIn("Mật khẩu", self.client.get("/login").text)

    def test_wrong_then_right_password(self):
        with self.env(VNSHOP_PASSWORD="bí-mật"):
            r = self.client.post("/login", data={"password": "sai"}, follow_redirects=False)
            self.assertEqual(r.status_code, 401)
            self.assertIn("không đúng", r.text)
            self.assertNotIn(auth.COOKIE, r.cookies)

            r = self.client.post("/login", data={"password": "bí-mật"}, follow_redirects=False)
            self.assertEqual((r.status_code, r.headers["location"]), (303, "/"))
            cookie = r.headers["set-cookie"]
            self.assertIn("HttpOnly", cookie)
            self.assertIn("Secure", cookie)
            self.assertIn("SameSite=lax", cookie)
            # Có cookie thì vượt qua lớp đăng nhập (trang chủ trả file index.html).
            self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 200)

            r = self.client.get("/logout", follow_redirects=False)
            self.assertEqual(r.headers["location"], "/login")

    def test_lockout_after_repeated_failures(self):
        with self.env(VNSHOP_PASSWORD="bí-mật"):
            for _ in range(auth.MAX_FAILURES):
                self.client.post("/login", data={"password": "sai"})
            r = self.client.post("/login", data={"password": "bí-mật"}, follow_redirects=False)
            self.assertEqual(r.status_code, 401)
            self.assertIn("Sai quá nhiều lần", r.text)

    def test_token_expiry_and_password_change(self):
        with self.env(VNSHOP_PASSWORD="a"):
            token = auth.make_token(now=1000)
            self.assertTrue(auth.valid_token(token, now=1001))
            self.assertFalse(auth.valid_token(token, now=1000 + auth.COOKIE_DAYS * 86400 + 1))
            self.assertFalse(auth.valid_token("rác", now=1001))
        with self.env(VNSHOP_PASSWORD="b"):
            self.assertFalse(auth.valid_token(token, now=1001))  # đổi mật khẩu -> cookie cũ hết hiệu lực


if __name__ == "__main__":
    unittest.main()
