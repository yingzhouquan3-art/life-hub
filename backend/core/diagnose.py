"""手机连不上时的自查。

手机访问要同时满足三件事，缺一条就连不上，而且现象都是「打不开网页」：

1. 后端确实监听在局域网地址上（用旧启动器启动时只监听本机）；
2. Windows 防火墙放行了这个端口（默认全部拦截入站连接）；
3. 手机和电脑在同一个网络里，且这个网络没有开客户端隔离。

前两条能在本机自动查出来，第三条只能给出判断线索。
查不出来的一律说「查不出来」，不猜。
"""
from __future__ import annotations

import socket
import subprocess
import sys
from typing import Optional

from backend.core.access import detect_lan_ip, detect_tailscale_ip

IS_WINDOWS = sys.platform == "win32"


def is_bound_to(address: str, port: int, timeout: float = 0.6) -> bool:
    """服务是不是真的在这个地址上监听。

    从本机连自己的局域网地址不经过防火墙的入站规则，
    所以这一项只反映「绑没绑」，不反映「防火墙放没放行」。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(timeout)
    try:
        probe.connect((address, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _powershell(script: str) -> Optional[str]:
    if not IS_WINDOWS:
        return None
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def firewall_allows(port: int) -> Optional[bool]:
    """有没有放行这个端口的入站规则。

    返回 None 表示查不出来（非 Windows，或查询本身失败），
    这时不要显示成「被拦截」——那是猜的。
    """
    # 从端口筛选器出发再取规则，比枚举全部规则再逐条查端口快一个数量级
    output = _powershell(
        "$rules = Get-NetFirewallPortFilter -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.LocalPort -eq {port} }} | "
        "Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { "
        "$_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' "
        "}; if ($rules) { 'yes' } else { 'no' }"
    )
    if output is None:
        return None
    return output.strip().lower() == "yes"


def network_category() -> Optional[str]:
    """当前联网的网络在 Windows 里被归为专用还是公用。

    公用网络下防火墙更严，而且按「专用」加的规则不会生效。
    """
    output = _powershell(
        "(Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -ne 'Disconnected' } "
        "| Select-Object -First 1 -ExpandProperty NetworkCategory)"
    )
    return output or None


def diagnose_mobile_access(port: int) -> dict:
    """把三道关卡逐条查一遍，并给出具体该做什么。"""
    lan_ip = detect_lan_ip()
    tailscale_ip = detect_tailscale_ip()
    target = tailscale_ip or lan_ip

    checks = []
    blocking = []

    if target is None:
        checks.append({
            "key": "address", "ok": False, "label": "找到可用的网络地址",
            "detail": "既没有局域网地址也没有 Tailscale 地址，电脑可能没连网络",
        })
        blocking.append("连上 WiFi，或用手机开热点让电脑连上去，然后刷新本页。")
        return {"port": port, "lan_ip": None, "tailscale_ip": None,
                "checks": checks, "actions": blocking, "ready": False}

    checks.append({
        "key": "address", "ok": True, "label": "找到可用的网络地址",
        "detail": f"{target}（{'Tailscale' if tailscale_ip else '局域网'}）",
    })

    bound = is_bound_to(target, port)
    checks.append({
        "key": "binding", "ok": bound, "label": "后端监听在这个地址上",
        "detail": "已监听" if bound
                  else "只监听了本机。多半是用了旧启动器，手机怎么都连不上",
    })
    if not bound:
        blocking.append(
            "先停止服务，改用「启动并允许手机访问.cmd」重新启动——"
            "旧的启动器只监听本机。"
        )

    allowed = firewall_allows(port)
    if allowed is None:
        checks.append({
            "key": "firewall", "ok": None, "label": "防火墙放行这个端口",
            "detail": "查不出来（非 Windows 或查询失败），请自行确认",
        })
    else:
        checks.append({
            "key": "firewall", "ok": allowed, "label": "防火墙放行这个端口",
            "detail": f"已有放行 {port} 的入站规则" if allowed
                      else f"没有放行 {port} 的规则，Windows 默认拦截所有入站连接",
        })
        if not allowed:
            blocking.append(
                f"以管理员身份运行 PowerShell，执行下面这条命令放行 {port} 端口。"
                "这会修改系统防火墙设置，所以需要你自己确认执行。"
            )

    category = network_category()
    if category:
        public = category.lower() == "public"
        checks.append({
            "key": "category", "ok": not public, "label": "网络类型是专用网络",
            "detail": f"当前是{'公用' if public else '专用'}网络"
                      + ("，公用网络下防火墙更严，按「专用」加的规则不会生效" if public else ""),
        })
        if public:
            blocking.append(
                "把当前 WiFi 改成「专用网络」：设置 → 网络和 Internet → WLAN → "
                "点当前网络 → 网络配置文件类型选「专用」。"
                "只在你信任的网络（家里、自己的手机热点）上这么做。"
            )

    return {
        "port": port,
        "lan_ip": lan_ip,
        "tailscale_ip": tailscale_ip,
        "target": target,
        "checks": checks,
        "actions": blocking,
        "firewall_command": (
            f'New-NetFirewallRule -DisplayName "我的生活中枢 {port}" '
            f"-Direction Inbound -Action Allow -Protocol TCP -LocalPort {port} "
            "-Profile Private"
        ),
        "ready": not blocking,
        "note": "客户端隔离查不出来：学校和公共 WiFi 常开这个，"
                "同网设备互相看不见。三项都通过还连不上，多半就是它，改用手机热点即可。",
    }
