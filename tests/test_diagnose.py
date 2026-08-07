"""手机连不上时的自查。

这个自查本身错了比没有更糟：
- 假阴性会让用户去重复添加已经存在的防火墙规则；
- 假阳性会告诉用户「防火墙没问题」，把人引到错误的方向。
两种都真实发生过，所以在这里各留一条回归。
"""
import socket
import unittest

from backend.core import diagnose


def free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class BindingCheckTests(unittest.TestCase):
    def test_detects_a_listening_socket(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)
        port = listener.getsockname()[1]
        self.assertTrue(diagnose.is_bound_to("127.0.0.1", port))

    def test_reports_nothing_listening(self):
        self.assertFalse(diagnose.is_bound_to("127.0.0.1", free_port()))


@unittest.skipUnless(diagnose.IS_WINDOWS, "防火墙查询只在 Windows 上有意义")
class FirewallCheckTests(unittest.TestCase):
    def test_unopened_port_is_not_reported_as_allowed(self):
        """回归：曾经把 LocalPorts='*' 的规则一律算作放行，

        于是查任何端口都返回「已放行」。假阳性比查不出来更糟——
        它会让用户以为防火墙没问题，从而找错方向。
        """
        for port in (9999, 1, 65500):
            with self.subTest(port=port):
                self.assertIs(
                    diagnose.firewall_allows(port), False,
                    f"端口 {port} 并没有专门的放行规则，不该报成已放行",
                )

    def test_query_finishes_quickly(self):
        """配对页会等这个结果。

        走规则侧逐条取端口筛选器要 96 秒，页面等不起，所以改用了 COM 接口。
        """
        import time

        started = time.time()
        diagnose.firewall_allows(9999)
        self.assertLess(time.time() - started, 15, "防火墙查询太慢，配对页会卡住")


class QueryImplementationTests(unittest.TestCase):
    """检查真正发出去的那条命令，而不是文件里的文字——

    源码注释里会提到走过的弯路，扫全文会把说明本身当成违规。
    """

    def captured_script(self, port=8766):
        captured = {}

        def fake(script):
            captured["script"] = script
            return "no"

        original = diagnose._powershell
        diagnose._powershell = fake
        try:
            diagnose.firewall_allows(port)
        finally:
            diagnose._powershell = original
        return captured["script"]

    def test_uses_the_com_api_not_the_broken_port_filter(self):
        """回归：Get-NetFirewallPortFilter 的全量枚举里找不到刚建的规则，

        用它判断会给出假阴性，页面于是让用户重复添加已经存在的规则。
        """
        script = self.captured_script()
        self.assertIn("HNetCfg.FwPolicy2", script)
        self.assertNotIn("Get-NetFirewallPortFilter", script)

    def test_wildcard_ports_are_tied_to_this_python(self):
        """回归：LocalPorts='*' 一律算放行会让任何端口都返回「已放行」。"""
        script = self.captured_script()
        self.assertIn("ApplicationName", script,
                      "通配端口必须绑定到具体程序才算数")


class ReportTests(unittest.TestCase):
    def test_unknown_results_are_not_reported_as_failures(self):
        original = diagnose.firewall_allows
        diagnose.firewall_allows = lambda port: None
        try:
            report = diagnose.diagnose_mobile_access(free_port())
        finally:
            diagnose.firewall_allows = original
        firewall = next(c for c in report["checks"] if c["key"] == "firewall")
        self.assertIsNone(firewall["ok"], "查不出来就是查不出来，不能显示成被拦截")

    def test_report_always_explains_what_it_cannot_see(self):
        report = diagnose.diagnose_mobile_access(free_port())
        self.assertIn("客户端隔离", report["note"])


if __name__ == "__main__":
    unittest.main()
