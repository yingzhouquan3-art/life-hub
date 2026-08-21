"""容器/云平台专用启动入口。

本地启动器继续使用 backend.serve，并拒绝公网地址。只有显式云端模式、
且已经配置足够长的密码时，这个入口才会监听容器的公网入口。
"""
from __future__ import annotations

import os

from backend.core.cloud_access import validate_cloud_configuration


def main() -> None:
    validate_cloud_configuration()
    port = int(os.environ.get("PORT", "8766"))
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
