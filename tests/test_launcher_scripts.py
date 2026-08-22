"""启动脚本的编码与自洽。

Windows PowerShell 5.1 读 .ps1 时，没有 BOM 的 UTF-8 会被当成本地代码页，
中文会变成乱码——注释还好，字符串里出现的乱码可能直接导致语法错误。
这个坑不会在别的测试里暴露，只会在用户双击时炸，所以在这里守住。
"""
import codecs
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

    def test_powershell_scripts_with_chinese_have_a_bom(self):
        """Windows PowerShell 5.1 没有 BOM 就按本地代码页读 .ps1，中文会全乱。

        .cmd 的规矩是「不许有中文」，.ps1 的规矩是「有中文就必须带 BOM」。
        """
        for path in sorted((ROOT / "windows").glob("*.ps1")):
            raw = path.read_bytes()
            has_chinese = bool(NON_ASCII.search(raw.decode("utf-8", errors="replace")))
            with self.subTest(script=path.name):
                if has_chinese:
                    self.assertTrue(
                        raw.startswith(codecs.BOM_UTF8),
                        f"{path.name} 含中文却没有 UTF-8 BOM，PowerShell 会读成乱码",
                    )

    def test_launchers_start_the_dual_socket_server(self):
        """必须走 backend.serve：uvicorn --host 只能绑一个地址，
        绑了局域网就会丢掉回环，桌面入口和配对页都打不开。"""
        for name in ("windows/start.ps1", "run.sh"):
            content = (ROOT / name).read_bytes().decode("utf-8-sig")
            with self.subTest(launcher=name):
                self.assertIn("backend.serve", content)
                self.assertNotIn(
                    "uvicorn backend.main:app", content,
                    f"{name} 仍在直接调 uvicorn，会丢掉回环监听",
                )

    def test_stop_script_can_recover_without_the_pid_file(self):
        """启动记录丢了也要能停掉服务，否则端口一直被占着。"""
        script = (ROOT / "windows" / "stop.ps1").read_bytes().decode("utf-8-sig")
        self.assertIn("Get-NetTCPConnection", script, "要能按端口反查进程")
        self.assertIn("Confirm-Action", script, "结束别的进程前必须先问过用户")

    def test_log_truncation_is_not_fatal(self):
        """上一个进程还占着日志文件时，不该让整个启动失败。"""
        script = (ROOT / "windows" / "start.ps1").read_bytes().decode("utf-8-sig")
        self.assertIn("Clear-LogFile", script)
        self.assertIn("catch", script)

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

    # ---------- 每日提醒 ----------

    def reminder(self):
        return (ROOT / "windows" / "remind.ps1").read_bytes().decode("utf-8-sig")

    def test_reminder_only_speaks_when_there_is_a_reason(self):
        """天天准点响的提醒，两周之内就会被无视。

        必须先问服务端「今天记了没有」，记过了就闭嘴——否则它训练用户
        忽略自己，之后真正该看的提醒也一起被忽略了。
        """
        script = self.reminder()
        self.assertIn("/api/life/overview", script)
        self.assertIn("completed_signals", script)
        # 判断必须在弹通知之前
        self.assertLess(script.index("completed_signals"), script.rindex("Show-Toast"))

    def test_reminder_stays_quiet_when_the_service_is_down(self):
        """服务没跑多半说明人不在电脑前，弹给空房间看没有意义。"""
        script = self.reminder()
        self.assertIn("catch", script)
        self.assertRegex(script, r"catch\s*\{[^}]*exit 0")

    def test_reminder_needs_no_extra_module(self):
        """要用户先装个模块才能收到提醒，等于这个功能不存在。"""
        script = self.reminder()
        self.assertNotIn("BurntToast", script)
        self.assertNotIn("Install-Module", script)
        self.assertIn("System.Windows.Forms", script)

    def test_reminder_does_not_use_the_silently_failing_toast_api(self):
        """WinRT 的 ToastNotification 要求 AppUserModelID 已在系统里注册。
        没注册时它**既不报错也不显示**：脚本退出码 0，用户什么都没看到。

        第一版就是这么悄悄失败的——我拿退出码当成了「用户看到了」。
        改用 NotifyIcon，它自己生成并注册 AUMID，不依赖前置注册。
        """
        script = self.reminder()
        self.assertNotIn("ToastNotificationManager", script)
        self.assertNotIn("Windows.UI.Notifications", script)
        self.assertIn("NotifyIcon", script)

    def test_reminder_keeps_the_tray_icon_alive_long_enough(self):
        """托盘图标一销毁，通知会跟着被收走。立刻退出等于没弹。"""
        script = self.reminder()
        self.assertIn("Start-Sleep", script)
        self.assertLess(script.index("ShowBalloonTip"), script.index("Dispose"))

    def test_reminder_script_has_no_stray_control_characters(self):
        """写这个脚本时踩过一次：\v 被当成垂直制表符写进了文件，
        AppId 那一行从中间断开，而肉眼完全看不出来。"""
        raw = (ROOT / "windows" / "remind.ps1").read_bytes()
        for bad in (0x0b, 0x0c, 0x00, 0x1a):
            with self.subTest(byte=hex(bad)):
                self.assertNotIn(bytes([bad]), raw)

    def test_setup_and_remove_agree_on_the_task_name(self):
        """名字对不上的话，「移除」会说没设置过，而提醒继续每天弹。"""
        setup = (ROOT / "windows" / "setup-reminder.ps1").read_bytes().decode("utf-8-sig")
        remove = (ROOT / "windows" / "remove-reminder.ps1").read_bytes().decode("utf-8-sig")
        pattern = re.compile(r'\$TaskName\s*=\s*"([^"]+)"')
        self.assertEqual(pattern.search(setup).group(1), pattern.search(remove).group(1))

    def test_setup_does_not_need_administrator(self):
        """要 UAC 的话每次改时间都得点一次同意，而它根本不需要。"""
        setup = (ROOT / "windows" / "setup-reminder.ps1").read_bytes().decode("utf-8-sig")
        self.assertNotIn("RunAsAdministrator", setup)
        self.assertNotIn("-User SYSTEM", setup)
        self.assertNotIn("Start-Process -Verb RunAs", setup)

    def test_reminder_survives_a_laptop_that_sleeps(self):
        """合盖是常态。电池上被跳过、错过不补，等于大部分日子都不会响。"""
        setup = (ROOT / "windows" / "setup-reminder.ps1").read_bytes().decode("utf-8-sig")
        self.assertIn("AllowStartIfOnBatteries", setup)
        self.assertIn("StartWhenAvailable", setup)


class ImportSideEffectTests(unittest.TestCase):
    """导入一个模块不该写用户的磁盘。

    init_db() 和 startup_checks() 曾经写在 backend/main.py 的模块层：
    任何人 import backend.main —— 测试脚本、命令行工具、编辑器的自动补全 ——
    都会在默认数据目录里建表，并可能落一份快照。这一条守住它别回去。
    """

    def test_startup_work_happens_in_lifespan_not_at_import(self):
        source = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        body = re.sub(r"#.*", "", source)
        for call in ("init_db()", "startup_checks()"):
            with self.subTest(call=call):
                # 模块层（顶格）调用一律不允许，只能出现在缩进的函数体里
                self.assertNotRegex(body, rf"(?m)^{re.escape(call)}\s*$")
        self.assertIn("lifespan", source)


if __name__ == "__main__":
    unittest.main()
