"""启动脚本的编码与自洽。

Windows PowerShell 5.1 读 .ps1 时，没有 BOM 的 UTF-8 会被当成本地代码页，
中文会变成乱码——注释还好，字符串里出现的乱码可能直接导致语法错误。
这个坑不会在别的测试里暴露，只会在用户双击时炸，所以在这里守住。
"""
import re
import unittest

from backend.core.config import ROOT

UTF8_BOM = b"\xef\xbb\xbf"
NON_ASCII = re.compile(r"[^\x00-\x7f]")


class LauncherScriptTests(unittest.TestCase):
    def powershell_scripts(self):
        return sorted((ROOT / "windows").glob("*.ps1"))

    def test_scripts_exist(self):
        self.assertTrue(self.powershell_scripts())

    def test_non_ascii_scripts_carry_a_bom(self):
        for path in self.powershell_scripts():
            raw = path.read_bytes()
            if NON_ASCII.search(raw.decode("utf-8-sig")):
                with self.subTest(script=path.name):
                    self.assertTrue(
                        raw.startswith(UTF8_BOM),
                        f"{path.name} 含中文但没有 UTF-8 BOM，"
                        "Windows PowerShell 5.1 会按本地代码页读成乱码",
                    )

    def test_scripts_are_valid_utf8(self):
        for path in self.powershell_scripts():
            with self.subTest(script=path.name):
                path.read_bytes().decode("utf-8-sig")

    def test_cmd_launchers_reference_existing_scripts(self):
        """双击的 .cmd 里写死了 .ps1 路径，改名后必须一起改。"""
        pattern = re.compile(r"windows\\([\w-]+\.ps1)")
        for path in sorted(ROOT.glob("*.cmd")):
            content = path.read_bytes().decode("utf-8", errors="replace")
            for referenced in pattern.findall(content):
                with self.subTest(launcher=path.name, script=referenced):
                    self.assertTrue(
                        (ROOT / "windows" / referenced).exists(),
                        f"{path.name} 引用了不存在的 {referenced}",
                    )

    def test_cmd_files_are_pure_ascii(self):
        """cmd.exe 按本地代码页读 .cmd，UTF-8 中文会变乱码并被当成命令执行。

        所以 .cmd 里一个中文都不能有——文件名可以是中文，内容不行。
        中文提示一律放进带 BOM 的 .ps1。
        """
        for path in sorted(ROOT.glob("*.cmd")):
            text = path.read_bytes().decode("utf-8", errors="replace")
            offenders = NON_ASCII.findall(text)
            with self.subTest(launcher=path.name):
                self.assertEqual(
                    offenders, [],
                    f"{path.name} 含非 ASCII 字符 {''.join(offenders)[:20]!r}，"
                    "会被 cmd 读成乱码",
                )

    def test_elevation_lives_in_powershell_not_cmd(self):
        """提权要在 PowerShell 里做：中文路径经 cmd 再转一层字符串容易出错。"""
        script = (ROOT / "windows" / "allow-mobile-access.ps1").read_bytes().decode("utf-8-sig")
        self.assertIn("-Verb RunAs", script)
        self.assertIn("$PSCommandPath", script, "重开自己要用 $PSCommandPath，不要拼路径")
        for path in sorted(ROOT.glob("*.cmd")):
            with self.subTest(launcher=path.name):
                self.assertNotIn(
                    "RunAs", path.read_bytes().decode("utf-8", errors="replace"),
                    f"{path.name} 不应自己做提权",
                )

    def test_firewall_script_only_touches_the_app_port(self):
        """这个脚本会改系统设置，范围必须收得很死。"""
        script = (ROOT / "windows" / "allow-mobile-access.ps1").read_bytes().decode("utf-8-sig")
        self.assertNotIn("Set-NetFirewallProfile", script, "不得改动防火墙开关")
        self.assertNotIn("-Enabled False", script, "不得关闭防火墙")
        self.assertIn("-Profile Private", script, "规则必须限定在专用网络")
        self.assertIn("Read-Host", script, "改网络类型前必须先问过用户")

    def test_mobile_launcher_asks_for_auto_binding(self):
        """手机访问模式必须让后端监听局域网，否则手机怎么都连不上。"""
        launcher = (ROOT / "启动并允许手机访问.cmd").read_bytes().decode("utf-8", errors="replace")
        self.assertIn("LIFE_HUB_HOST=auto", launcher.replace('"', ""))


if __name__ == "__main__":
    unittest.main()
