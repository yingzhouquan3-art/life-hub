"""启动服务器时的地址绑定。

最重要的一条：**回环永远监听**。
uvicorn 的 --host 只能绑一个地址，绑了局域网就丢掉回环，
于是桌面入口、配对页、诊断接口全都打不开——用户只会看到「启动失败」。
"""
import socket
import unittest

from backend import serve


def free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class BuildSocketsTests(unittest.TestCase):
    def build(self, extra_host):
        port = free_port()
        sockets, bound = serve.build_sockets(port, extra_host)
        self.addCleanup(lambda: [s.close() for s in sockets])
        return sockets, bound, port

    def test_loopback_is_always_bound(self):
        for extra in (None, "", "127.0.0.1"):
            with self.subTest(extra=extra):
                sockets, bound, _ = self.build(extra)
                self.assertEqual(bound, ["127.0.0.1"])
                self.assertEqual(len(sockets), 1)

    def test_extra_host_is_added_next_to_loopback(self):
        from backend.core.access import detect_lan_ip

        address = detect_lan_ip()
        if not address:
            self.skipTest("这台机器当前没有局域网地址")
        sockets, bound, _ = self.build(address)
        self.assertIn("127.0.0.1", bound, "回环必须仍然在监听")
        self.assertIn(address, bound)
        self.assertEqual(len(sockets), 2)

    def test_unbindable_extra_host_does_not_kill_loopback(self):
        """多绑一个地址失败时，桌面照样要能用。"""
        sockets, bound, _ = self.build("203.0.113.7")  # 本机不可能拥有的地址
        self.assertEqual(bound, ["127.0.0.1"])
        self.assertEqual(len(sockets), 1)

    def test_port_in_use_is_reported_not_silently_shared(self):
        port = free_port()
        holder = socket.socket()
        holder.bind(("127.0.0.1", port))
        holder.listen(1)
        self.addCleanup(holder.close)
        with self.assertRaises(OSError):
            serve.open_socket("127.0.0.1", port)


class ArgumentTests(unittest.TestCase):
    def test_wildcard_preference_is_refused(self):
        self.assertEqual(serve.main(["--host-preference", "0.0.0.0", "--port", "1"]), 2)


if __name__ == "__main__":
    unittest.main()
