"""可选云端模式：公网入口必须先经过单用户登录。"""
import os
import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from backend import main
from backend.core import cloud_access


class CloudAccessUnitTests(unittest.TestCase):
    def setUp(self):
        cloud_access.clear_login_failures()
        cloud_access._signing_key.cache_clear()
        self.env = patch.dict(
            os.environ,
            {"LIFE_HUB_MODE": "cloud", "LIFE_HUB_PASSWORD": "correct-horse-battery"},
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        cloud_access.clear_login_failures()
        cloud_access._signing_key.cache_clear()

    def test_cloud_configuration_requires_a_long_password(self):
        cloud_access.validate_cloud_configuration()
        with patch.dict(os.environ, {"LIFE_HUB_PASSWORD": "short"}, clear=False):
            with self.assertRaises(RuntimeError):
                cloud_access.validate_cloud_configuration()

    def test_signed_session_expires_and_rejects_tampering(self):
        session = cloud_access.create_session(now=1000)
        self.assertTrue(cloud_access.session_valid(session, now=1001))
        self.assertFalse(cloud_access.session_valid(session + "x", now=1001))
        self.assertFalse(
            cloud_access.session_valid(session, now=1000 + cloud_access.SESSION_SECONDS + 1)
        )

    def test_five_wrong_passwords_throttle_that_client(self):
        for index in range(cloud_access.MAX_FAILURES):
            result = cloud_access.attempt_login("wrong", "client-a", now=1000 + index)
            self.assertFalse(result.ok)
        blocked = cloud_access.attempt_login("correct-horse-battery", "client-a", now=1010)
        self.assertFalse(blocked.ok)
        self.assertGreater(blocked.retry_after, 0)
        other = cloud_access.attempt_login("correct-horse-battery", "client-b", now=1010)
        self.assertTrue(other.ok)


class CloudAccessHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn

        cls.env = patch.dict(
            os.environ,
            {"LIFE_HUB_MODE": "cloud", "LIFE_HUB_PASSWORD": "correct-horse-battery"},
            clear=False,
        )
        cls.env.start()
        # 端口写死会撞上本机正在跑的实例，请求就打到别人身上了：
        # 那会让这组守门禁的测试给出假结果。改成让系统分配一个空闲端口，
        # 并断言服务真的起来了，起不来就直接失败，不要沉默地测别人。
        cls.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cls.sock.bind(("127.0.0.1", 0))
        cls.sock.listen(64)
        cls.port = cls.sock.getsockname()[1]
        cls.config = uvicorn.Config(main.app, log_level="error")
        cls.server = uvicorn.Server(cls.config)
        cls.thread = threading.Thread(
            target=lambda: cls.server.run(sockets=[cls.sock]), daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)
        if not cls.server.started:
            raise RuntimeError("测试用的服务没起来，后面的断言不能算数")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        cls.env.stop()

    def setUp(self):
        cloud_access.clear_login_failures()
        cloud_access._signing_key.cache_clear()

    def tearDown(self):
        cloud_access.clear_login_failures()
        cloud_access._signing_key.cache_clear()

    def request(self, path, payload=None, cookie=None, follow=True):
        headers = {}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers,
            method="POST" if payload is not None else "GET",
        )
        opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect())
        try:
            response = opener.open(request, timeout=10)
            return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_health_is_public_but_life_data_is_not(self):
        self.assertEqual(self.request("/api/health")[0], 200)
        self.assertEqual(self.request("/api/state")[0], 401)
        status, headers, _ = self.request("/", follow=False)
        self.assertEqual(status, 303)
        self.assertTrue(headers["location"].startswith("/login.html"))

    def test_login_cookie_unlocks_data_and_logout_locks_it_again(self):
        self.assertEqual(self.request("/api/auth/login", {"password": "wrong"})[0], 401)
        status, headers, _ = self.request(
            "/api/auth/login", {"password": "correct-horse-battery"}
        )
        self.assertEqual(status, 200)
        set_cookie = headers["set-cookie"]
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("Secure", set_cookie)
        cookie = set_cookie.split(";", 1)[0]
        self.assertEqual(self.request("/api/state", cookie=cookie)[0], 200)
        self.assertEqual(self.request("/api/auth/logout", {}, cookie=cookie)[0], 200)
        self.assertEqual(self.request("/api/state")[0], 401)


class LocalAccessRegressionTests(unittest.TestCase):
    def test_local_mode_still_needs_no_login(self):
        with patch.dict(os.environ, {"LIFE_HUB_MODE": "local"}, clear=False):
            self.assertFalse(cloud_access.cloud_mode_enabled())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


if __name__ == "__main__":
    unittest.main()
