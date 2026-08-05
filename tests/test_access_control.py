"""非本机访问的门禁。

桌面一直是回环地址，没有门禁需求。手机连进来之后就不同了：
监听地址一旦不是回环，任何能到达这台机器的设备都能读到全部生活数据。
"""
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from backend.core import access, config


class AccessRuleTests(unittest.TestCase):
    """规则本身。做成纯函数就是为了能直接枚举各种来源与路径的组合。"""

    def setUp(self):
        self.original_dir = config.DATA_DIR
        self.original_file = access.TOKEN_FILE
        self.temp_dir = tempfile.TemporaryDirectory()
        access.TOKEN_FILE = Path(self.temp_dir.name) / "access-token.txt"

    def tearDown(self):
        access.TOKEN_FILE = self.original_file
        self.temp_dir.cleanup()

    def test_loopback_never_needs_a_token(self):
        for host in ("127.0.0.1", "::1", "localhost"):
            with self.subTest(host=host):
                self.assertTrue(access.access_allowed(host, "/api/state", None))

    def test_remote_api_access_requires_a_token(self):
        self.assertFalse(access.access_allowed("100.101.102.103", "/api/state", None))
        self.assertFalse(access.access_allowed("100.101.102.103", "/api/state", "wrong"))
        self.assertTrue(
            access.access_allowed("100.101.102.103", "/api/state", access.get_or_create_token())
        )

    def test_static_shell_is_open_without_a_token(self):
        """Service Worker 与 manifest 的请求带不上自定义头，外壳必须免鉴权。"""
        for path in ("/m/", "/m/app.js", "/m/sw.js", "/m/manifest.webmanifest", "/pair.html", "/"):
            with self.subTest(path=path):
                self.assertTrue(access.access_allowed("100.101.102.103", path, None))

    def test_shell_carries_no_data(self):
        """外壳免鉴权的前提是它不含数据——这里守住这个前提。"""
        for name in ("index.html", "app.js", "sw.js", "manifest.webmanifest"):
            content = (config.FRONTEND / "m" / name).read_text(encoding="utf-8")
            self.assertNotIn("ledger.db", content)
            self.assertNotIn("access-token", content)

    def test_unknown_host_is_treated_as_remote(self):
        self.assertFalse(access.access_allowed(None, "/api/state", None))
        self.assertFalse(access.access_allowed("", "/api/state", None))

    def test_token_is_stable_until_reset(self):
        first = access.get_or_create_token()
        self.assertEqual(first, access.get_or_create_token())
        second = access.reset_token()
        self.assertNotEqual(first, second)
        self.assertFalse(
            access.access_allowed("100.101.102.103", "/api/state", first),
            "换过令牌之后旧令牌必须立刻失效",
        )

    def test_token_is_long_enough_to_be_a_secret(self):
        self.assertGreaterEqual(len(access.get_or_create_token()), 24)

    def test_tailscale_range_is_recognised(self):
        self.assertTrue(access.is_tailscale_address("100.64.0.1"))
        self.assertTrue(access.is_tailscale_address("100.127.255.254"))
        self.assertFalse(access.is_tailscale_address("192.168.1.5"))
        self.assertFalse(access.is_tailscale_address("100.128.0.1"))
        self.assertFalse(access.is_tailscale_address("not-an-ip"))


class LiveServerTests(unittest.TestCase):
    """跑一个真服务器，确认中间件真的接上了。

    本机请求走的是回环分支，所以这里验证的是「桌面使用不受影响」。
    远端分支由上面的纯函数测试覆盖——伪造远端来源需要改网络栈，不值得。
    """

    @classmethod
    def setUpClass(cls):
        import uvicorn

        from backend import main

        cls.config = uvicorn.Config(main.app, host="127.0.0.1", port=8791, log_level="error")
        cls.server = uvicorn.Server(cls.config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(80):
            if cls.server.started:
                break
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:8791{path}", timeout=10) as response:
            return response.status, response.read()

    def test_local_api_still_works_without_a_token(self):
        status, _ = self.get("/api/today")
        self.assertEqual(status, 200)

    def test_mobile_shell_is_served(self):
        status, body = self.get("/m/")
        self.assertEqual(status, 200)
        self.assertIn("一句话记录", body.decode("utf-8"))

    def test_service_worker_and_manifest_are_served(self):
        for path in ("/m/sw.js", "/m/manifest.webmanifest", "/m/icon.svg"):
            with self.subTest(path=path):
                status, _ = self.get(path)
                self.assertEqual(status, 200)

    def test_pairing_page_is_served(self):
        status, body = self.get("/pair.html")
        self.assertEqual(status, 200)
        self.assertIn("手机配对", body.decode("utf-8"))

    def test_pairing_endpoint_returns_token_for_local_request(self):
        import json

        status, body = self.get("/api/access/pairing")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["token"])
        self.assertEqual(payload["token_header"], "X-Life-Token")

    def test_desktop_app_still_loads(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertGreater(len(body), 1000)


if __name__ == "__main__":
    unittest.main()
