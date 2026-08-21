"""单用户云端访问门禁。

[POS] backend/core/cloud_access.py — 云端密码、签名会话与登录节流
[INPUT] LIFE_HUB_MODE / LIFE_HUB_PASSWORD 环境变量
[OUTPUT] 小型认证接口；不认识任何生活模块，也不读取账本

云端模式必须显式开启。密码只存在部署平台的 Secret 环境变量中，
不会写入数据库、日志或仓库。会话是带到期时间的 HMAC 签名 cookie，
服务端不需要维护另一份用户表。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

CLOUD_MODE = "cloud"
COOKIE_NAME = "lifehub_session"
SESSION_SECONDS = 30 * 24 * 60 * 60
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 5 * 60
MIN_PASSWORD_LENGTH = 12

_failure_lock = threading.Lock()
_failures: dict[str, list[float]] = {}


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    session: Optional[str] = None
    retry_after: int = 0


def cloud_mode_enabled() -> bool:
    return os.environ.get("LIFE_HUB_MODE", "").strip().lower() == CLOUD_MODE


def configured_password() -> str:
    return os.environ.get("LIFE_HUB_PASSWORD", "")


def validate_cloud_configuration() -> None:
    """云端启动前快速失败，避免产生一个裸露或永远登不进去的实例。"""
    if not cloud_mode_enabled():
        raise RuntimeError("云端启动需要 LIFE_HUB_MODE=cloud")
    if len(configured_password()) < MIN_PASSWORD_LENGTH:
        raise RuntimeError(f"LIFE_HUB_PASSWORD 至少需要 {MIN_PASSWORD_LENGTH} 个字符")


@lru_cache(maxsize=8)
def _signing_key(password: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), b"life-hub-session-v1", 120_000
    )


def _signature(payload: str, password: str) -> str:
    return hmac.new(_signing_key(password), payload.encode("ascii"), hashlib.sha256).hexdigest()


def create_session(now: Optional[float] = None) -> str:
    password = configured_password()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RuntimeError("云端密码尚未正确配置")
    expires = int((time.time() if now is None else now) + SESSION_SECONDS)
    payload = f"v1.{expires}.{secrets.token_urlsafe(18)}"
    return f"{payload}.{_signature(payload, password)}"


def session_valid(value: Optional[str], now: Optional[float] = None) -> bool:
    if not value:
        return False
    password = configured_password()
    if len(password) < MIN_PASSWORD_LENGTH:
        return False
    try:
        version, expires_text, nonce, supplied = value.split(".", 3)
        expires = int(expires_text)
    except (TypeError, ValueError):
        return False
    if version != "v1" or not nonce or expires < int(time.time() if now is None else now):
        return False
    payload = f"{version}.{expires}.{nonce}"
    return hmac.compare_digest(supplied, _signature(payload, password))


def _recent_failures(client_id: str, now: float) -> list[float]:
    cutoff = now - FAILURE_WINDOW_SECONDS
    return [stamp for stamp in _failures.get(client_id, []) if stamp > cutoff]


def attempt_login(password: str, client_id: Optional[str], now: Optional[float] = None) -> LoginResult:
    """验证一次登录，并把连续猜错限制在一个很小的时间窗口里。"""
    stamp = time.time() if now is None else now
    key = client_id or "unknown"
    with _failure_lock:
        recent = _recent_failures(key, stamp)
        _failures[key] = recent
        if len(recent) >= MAX_FAILURES:
            retry_after = max(1, int(FAILURE_WINDOW_SECONDS - (stamp - recent[0])))
            return LoginResult(False, retry_after=retry_after)

        expected = configured_password()
        if len(expected) >= MIN_PASSWORD_LENGTH and secrets.compare_digest(password, expected):
            _failures.pop(key, None)
            return LoginResult(True, session=create_session(stamp))

        recent.append(stamp)
        _failures[key] = recent
        return LoginResult(False)


def clear_login_failures() -> None:
    """测试与运维用；不参与正常请求流程。"""
    with _failure_lock:
        _failures.clear()
