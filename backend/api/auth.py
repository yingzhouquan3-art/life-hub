"""云端单用户登录接口；本地模式不需要调用。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.core.cloud_access import (
    COOKIE_NAME,
    SESSION_SECONDS,
    attempt_login,
    cloud_mode_enabled,
    session_valid,
)

router = APIRouter()


class LoginIn(BaseModel):
    password: str = Field(..., min_length=1, max_length=256)


@router.get("/api/health")
def health():
    """部署平台的公开健康检查，不读取或泄露任何生活数据。"""
    return {"ok": True, "mode": "cloud" if cloud_mode_enabled() else "local"}


@router.get("/api/auth/status")
def auth_status(request: Request):
    cloud = cloud_mode_enabled()
    authenticated = (not cloud) or session_valid(request.cookies.get(COOKIE_NAME))
    return {"mode": "cloud" if cloud else "local", "authenticated": authenticated}


@router.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    if not cloud_mode_enabled():
        return JSONResponse({"ok": True, "mode": "local"})
    client = request.client.host if request.client else None
    result = attempt_login(body.password, client)
    if result.retry_after:
        return JSONResponse(
            {"detail": "尝试次数过多，请稍后再试。"},
            status_code=429,
            headers={"Retry-After": str(result.retry_after)},
        )
    if not result.ok:
        return JSONResponse({"detail": "密码不正确。"}, status_code=401)
    response = JSONResponse({"ok": True, "mode": "cloud"})
    response.set_cookie(
        COOKIE_NAME,
        result.session,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/api/auth/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
    return response
