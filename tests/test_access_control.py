"""非本机访问的门禁。

桌面一直是回环地址，没有门禁需求。手机连进来之后就不同了：
监听地址一旦不是回环，任何能到达这台机器的设备都能读到全部生活数据。
"""
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from backend.core import access, config
from backend.core import db as db_core


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


class BindHostTests(unittest.TestCase):
    """监听地址的选择。

    最重要的一条：找不到目标网络时一律退回回环。
    宁可手机连不上，也不能在用户以为「没连上」的时候悄悄暴露出去。
    """

    def test_default_is_loopback_only(self):
        for preference in ("", None, "local", "127.0.0.1", "localhost"):
            with self.subTest(preference=preference):
                self.assertEqual(access.resolve_bind_host(preference)["host"], "127.0.0.1")

    def test_wildcard_is_refused(self):
        for preference in ("0.0.0.0", "::"):
            with self.subTest(preference=preference):
                with self.assertRaises(ValueError):
                    access.resolve_bind_host(preference)

    def test_public_address_is_refused(self):
        with self.assertRaises(ValueError):
            access.resolve_bind_host("8.8.8.8")

    def test_explicit_private_address_is_accepted(self):
        result = access.resolve_bind_host("192.168.1.20")
        self.assertEqual(result["host"], "192.168.1.20")
        self.assertEqual(result["mode"], "lan")

    def test_explicit_tailscale_address_is_accepted(self):
        result = access.resolve_bind_host("100.101.102.103")
        self.assertEqual(result["mode"], "tailscale")

    def test_missing_network_falls_back_to_loopback(self):
        original = access.detect_tailscale_ip
        access.detect_tailscale_ip = lambda: None
        try:
            result = access.resolve_bind_host("tailscale")
        finally:
            access.detect_tailscale_ip = original
        self.assertEqual(result["host"], "127.0.0.1")
        self.assertEqual(result["mode"], "local")
        self.assertIn("退回", result["reason"])

    def test_auto_prefers_tailscale_then_lan(self):
        original_ts, original_lan = access.detect_tailscale_ip, access.detect_lan_ip
        try:
            access.detect_tailscale_ip = lambda: "100.1.2.3"
            access.detect_lan_ip = lambda: "192.168.1.9"
            self.assertEqual(access.resolve_bind_host("auto")["mode"], "tailscale")

            access.detect_tailscale_ip = lambda: None
            self.assertEqual(access.resolve_bind_host("auto")["host"], "192.168.1.9")

            access.detect_lan_ip = lambda: None
            self.assertEqual(access.resolve_bind_host("auto")["host"], "127.0.0.1")
        finally:
            access.detect_tailscale_ip, access.detect_lan_ip = original_ts, original_lan

    def test_virtual_and_placeholder_addresses_are_not_lan(self):
        """这些看着像内网，绑上去手机根本连不通。"""
        for address in ("169.254.83.107", "198.18.0.1", "100.64.0.1", "127.0.0.1"):
            with self.subTest(address=address):
                self.assertFalse(access.is_private_lan_address(address))

    def test_real_private_ranges_are_lan(self):
        for address in ("192.168.10.49", "10.0.0.5", "172.16.3.4"):
            with self.subTest(address=address):
                self.assertTrue(access.is_private_lan_address(address))

    def test_detect_lan_ip_returns_a_usable_address_or_none(self):
        found = access.detect_lan_ip()
        if found is not None:
            self.assertTrue(access.is_private_lan_address(found))


class LiveServerTests(unittest.TestCase):
    """跑一个真服务器，确认中间件真的接上了。

    本机请求走的是回环分支，所以这里验证的是「桌面使用不受影响」。
    远端分支由上面的纯函数测试覆盖——伪造远端来源需要改网络栈，不值得。
    """

    @classmethod
    def setUpClass(cls):
        import uvicorn

        from backend import main

        # 端口写死会撞上本机正在跑的实例，请求就打到别人身上了：
        # 那会让这组守门禁的测试给出假结果。改成让系统分配一个空闲端口，
        # 并断言服务真的起来了，起不来就直接失败，不要沉默地测别人。
        # 起真服务前先把数据库指到临时目录：这组测试会真的读写库，
        # 不重定向的话它跑的是用户自己的账本。
        cls.original_db_path = db_core.current_path()
        cls.db_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(cls.db_dir.name) / "ledger.db")
        main.init_db()

        cls.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cls.sock.bind(("127.0.0.1", 0))
        cls.sock.listen(64)
        cls.port = cls.sock.getsockname()[1]
        cls.config = uvicorn.Config(main.app, log_level="error")
        cls.server = uvicorn.Server(cls.config)
        cls.thread = threading.Thread(
            target=lambda: cls.server.run(sockets=[cls.sock]), daemon=True)
        cls.thread.start()
        for _ in range(80):
            if cls.server.started:
                break
            time.sleep(0.05)
        if not cls.server.started:
            raise RuntimeError("测试用的服务没起来，后面的断言不能算数")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        db_core.use_database(cls.original_db_path)
        cls.db_dir.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as response:
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
