"""非本机访问的门禁。

桌面上一直是 127.0.0.1，没有门禁的必要。手机要连进来就不同了：
一旦监听地址不是回环，任何能到达这台机器的设备都能读到全部生活数据。

所以规则很简单：

- 回环地址（本机浏览器）照旧放行，桌面使用体验完全不变；
- 其他来源访问 `/api/*` 必须带 token，否则 401；
- 静态外壳（页面、脚本、图标）不需要 token —— 它们不含任何数据，
  而且 Service Worker 与 manifest 请求带不上自定义头。

token 存在 data/access-token.txt，只在本机生成，不进版本库。
它不是给外网用的凭据：这套东西应当只在 Tailscale 这类私有网络里暴露，
token 防的是「同一私有网络里的其他设备」，不是公网攻击者。
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


def describe_access(port: int) -> dict:
    """给启动器与手机端配对页用的访问信息。"""
    tailscale_ip = detect_tailscale_ip()
    return {
        "local_url": f"http://127.0.0.1:{port}",
        "tailscale_ip": tailscale_ip,
        "mobile_url": f"http://{tailscale_ip}:{port}/m/" if tailscale_ip else None,
        "token": get_or_create_token(),
        "token_header": TOKEN_HEADER,
    }
