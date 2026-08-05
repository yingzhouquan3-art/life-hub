"""HTTP 路由层。

每个模块一个 APIRouter，main.py 只负责按顺序装配。
路由只做参数校验与调用，业务计算留在 modules/ 与 views/。
"""
