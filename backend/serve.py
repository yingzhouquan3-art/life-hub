"""启动服务器。

为什么不直接用 `uvicorn backend.main:app --host X`：

uvicorn 的 `--host` 只能绑一个地址。绑了局域网地址，回环就不通了——
于是桌面入口 http://127.0.0.1:8766 打不开、配对页打不开（它只允许本机访问）、
启动器的「是否已在运行」检测也跟着失效。

所以这里自己创建好 socket 再交给 uvicorn：**回环永远监听**，
需要手机访问时再额外加一个局域网或 Tailscale 地址。
这样既保住桌面体验，又不需要 0.0.0.0。
"""
from __future__ import annotations

import argparse
import socket
import sys
from typing import Optional

from backend.core.access import resolve_bind_host

LOOPBACK = "127.0.0.1"


def open_socket(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # 不设 SO_REUSEADDR：端口已被占用时应当直接失败，
    # 而不是让两个实例同时抢同一个端口，那会得到时好时坏的诡异现象。
    try:
        sock.bind((host, port))
        sock.listen(128)
    except OSError:
        sock.close()   # 绑不上就别把这个 fd 留着
        raise
    sock.set_inheritable(True)
    return sock


def build_sockets(port: int, extra_host: Optional[str]) -> tuple[list[socket.socket], list[str]]:
    """回环必开；extra_host 与回环不同时再多开一个。"""
    sockets = [open_socket(LOOPBACK, port)]
    bound = [LOOPBACK]
    if extra_host and extra_host != LOOPBACK:
        try:
            sockets.append(open_socket(extra_host, port))
            bound.append(extra_host)
        except OSError as exc:
            # 多绑一个地址失败不该拖垮整个服务：桌面照样能用，
            # 只是手机连不上，配对页的自查会如实显示出来。
            print(f"[serve] 无法监听 {extra_host}:{port}（{exc}），手机将连不上", flush=True)
    return sockets, bound


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="启动我的生活中枢")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--host-preference", default="",
        help="local / lan / tailscale / auto / 具体地址；不填只监听本机",
    )
    parser.add_argument("--reload", action="store_true", help="改代码自动重启（开发用）")
    args = parser.parse_args(argv)

    try:
        binding = resolve_bind_host(args.host_preference)
    except ValueError as exc:
        print(f"[serve] {exc}", file=sys.stderr)
        return 2

    print(f"[serve] {binding['reason']}", flush=True)

    if args.reload:
        # 自动重载要求 uvicorn 自己管理 socket，这时只能绑一个地址。
        # 开发场景下以桌面为主，所以固定回环。
        import uvicorn

        print("[serve] --reload 模式只监听本机", flush=True)
        uvicorn.run("backend.main:app", host=LOOPBACK, port=args.port, reload=True)
        return 0

    import uvicorn

    from backend import main as app_module

    sockets, bound = build_sockets(args.port, binding["host"])
    for host in bound:
        print(f"[serve] 监听 http://{host}:{args.port}", flush=True)
    if len(bound) == 1:
        print("[serve] 只监听本机，手机连不上；需要手机访问请用 --host-preference auto",
              flush=True)
    else:
        print(f"[serve] 手机配对页面：http://{LOOPBACK}:{args.port}/pair.html", flush=True)

    config = uvicorn.Config(app_module.app, log_level="info")
    server = uvicorn.Server(config)
    server.run(sockets=sockets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
