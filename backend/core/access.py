"""非本机访问的门禁。

桌面上一直是 127.0.0.1，没有门禁的必要。手机要连进来就不同了：
一旦监听地址不是回环，任何能到达这台机器的设备都能读到全部生活数据。

所以规则很简单：

- 回环地址（本机浏览器）照旧放行，桌面使用体验完全不变；
- 其他来源访问 `/api/*` 必须带 token，否则 401；
- 静态外壳（页面、脚本、图标）不需要 token —— 它们不含任何数据，
  而且 Service Worker 与 manifest 请求带不上自定义头。

token 存在 data/access-token.txt，只在本机生成，不进版本库。
它不是给外网用的凭据：这套东西应当只在私有网络（Tailscale 或你自己的家庭 WiFi）里暴露，
token 防的是「同一网络里的其他设备」，不是公网攻击者。
"""
from __future__ import annotations

import ipaddress
import secrets
import socket
from pathlib import Path
from typing import Optional

from backend.core.config import DATA_DIR

TOKEN_FILE = DATA_DIR / "access-token.txt"
TOKEN_HEADER = "X-Life-Token"

# 需要 token 的路径前缀。静态外壳不在其中。
GUARDED_PREFIXES = ("/api/",)

# Tailscale 给设备分配的地址段
_TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")

# 这些段看起来像内网，其实是虚拟网卡或没连上网时的占位地址，绑上去手机连不通
_NOT_REAL_LAN = (
    ipaddress.ip_network("169.254.0.0/16"),   # 没拿到 DHCP 时的自动地址
    ipaddress.ip_network("198.18.0.0/15"),    # 基准测试保留段，常被 VPN 客户端占用
    _TAILSCALE_NET,
)


def get_or_create_token() -> str:
    """读取本机 token，不存在就生成一个。"""
    if TOKEN_FILE.exists():
        existing = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    token = secrets.token_urlsafe(24)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    return token


def reset_token() -> str:
    """换一个新 token。手机丢了或者 token 泄漏时用。"""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    return get_or_create_token()


def is_loopback(host: Optional[str]) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def is_tailscale_address(host: Optional[str]) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host) in _TAILSCALE_NET
    except ValueError:
        return False


def path_needs_token(path: str) -> bool:
    return path.startswith(GUARDED_PREFIXES)


def access_allowed(client_host: Optional[str], path: str, provided_token: Optional[str]) -> bool:
    """判断一次请求是否放行。

    纯函数，不碰请求对象，方便直接测试各种来源与路径的组合。
    """
    if is_loopback(client_host):
        return True
    if not path_needs_token(path):
        return True
    if not provided_token:
        return False
    return secrets.compare_digest(provided_token, get_or_create_token())


def detect_tailscale_ip() -> Optional[str]:
    """找出本机的 Tailscale 地址；没装或没连上就返回 None。"""
    try:
        _, _, addresses = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        return None
    for address in addresses:
        if is_tailscale_address(address):
            return address
    return None


def is_private_lan_address(host: Optional[str]) -> bool:
    """是不是一个真正能让同网设备连过来的内网地址。"""
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if not address.is_private or address.is_loopback:
        return False
    return not any(address in network for network in _NOT_REAL_LAN)


def detect_lan_ip() -> Optional[str]:
    """本机在当前网络里的地址。

    用「往外发一个 UDP 包时系统选了哪块网卡」来判断，比按网卡名字猜可靠：
    一台机器上常同时存在虚拟网卡、VPN 网卡和没连上的网卡。
    这里不会真的发出任何数据，只是让内核做一次路由选择。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("223.5.5.5", 80))
        candidate = probe.getsockname()[0]
        if is_private_lan_address(candidate):
            return candidate
    except OSError:
        pass
    finally:
        probe.close()

    # 没连网络时退回枚举，仍然要滤掉虚拟网卡与占位地址
    try:
        _, _, addresses = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        return None
    for address in addresses:
        if is_private_lan_address(address):
            return address
    return None


def resolve_bind_host(preference: Optional[str]) -> dict:
    """把启动器给的偏好翻译成真正要监听的地址。

    找不到目标网络时一律退回回环——宁可手机连不上，也不能悄悄暴露出去。
    """
    wanted = (preference or "").strip().lower()
    if wanted in ("", "local", "127.0.0.1", "localhost"):
        return {"host": "127.0.0.1", "mode": "local", "reason": "只监听本机"}
    if wanted in ("0.0.0.0", "::"):
        raise ValueError("拒绝监听 0.0.0.0：那会把生活数据暴露给你当时连着的任何一个网络")
    if wanted == "tailscale":
        found = detect_tailscale_ip()
        if found:
            return {"host": found, "mode": "tailscale", "reason": "监听 Tailscale 私有网络"}
        return {"host": "127.0.0.1", "mode": "local",
                "reason": "没有找到 Tailscale 地址，已退回只监听本机"}
    if wanted == "lan":
        found = detect_lan_ip()
        if found:
            return {"host": found, "mode": "lan", "reason": "监听当前局域网"}
        return {"host": "127.0.0.1", "mode": "local",
                "reason": "没有找到局域网地址，已退回只监听本机"}
    if wanted == "auto":
        found = detect_tailscale_ip()
        if found:
            return {"host": found, "mode": "tailscale", "reason": "监听 Tailscale 私有网络"}
        found = detect_lan_ip()
        if found:
            return {"host": found, "mode": "lan", "reason": "没有 Tailscale，改为监听当前局域网"}
        return {"host": "127.0.0.1", "mode": "local",
                "reason": "既没有 Tailscale 也没有局域网地址，已退回只监听本机"}
    if is_tailscale_address(wanted) or is_private_lan_address(wanted):
        mode = "tailscale" if is_tailscale_address(wanted) else "lan"
        return {"host": wanted, "mode": mode, "reason": f"监听指定地址 {wanted}"}
    raise ValueError(f"拒绝监听 {preference}：只允许回环、Tailscale 或内网地址")


def describe_access(port: int) -> dict:
    """给启动器与手机端配对页用的访问信息。"""
    tailscale_ip = detect_tailscale_ip()
    lan_ip = detect_lan_ip()
    # 有 Tailscale 就优先用它：出门在外也连得上，且不依赖当前 WiFi 是否隔离客户端
    preferred = tailscale_ip or lan_ip
    return {
        "local_url": f"http://127.0.0.1:{port}",
        "tailscale_ip": tailscale_ip,
        "lan_ip": lan_ip,
        "mode": "tailscale" if tailscale_ip else ("lan" if lan_ip else None),
        "mobile_url": f"http://{preferred}:{port}/m/" if preferred else None,
        "lan_url": f"http://{lan_ip}:{port}/m/" if lan_ip else None,
        "token": get_or_create_token(),
        "token_header": TOKEN_HEADER,
    }
