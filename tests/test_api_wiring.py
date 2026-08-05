"""路由装配契约。

拆成多个 APIRouter 之后，"某个模块的路由忘了挂上去"和"请求模型的注解漏了 import"
都不会在导入时报错，只会在真正收到请求时才炸。这里把两件事都变成测试。
"""
import unittest

from backend import main
from backend.api import (
    fitness,
    goals,
    ledger,
    nutrition,
    platform,
    recovery,
    reflection,
    rhythm,
    study,
    views,
)

ROUTERS = {
    "platform": platform.router,
    "ledger": ledger.router,
    "fitness": fitness.router,
    "nutrition": nutrition.router,
    "recovery": recovery.router,
    "study": study.router,
    "rhythm": rhythm.router,
    "reflection": reflection.router,
    "goals": goals.router,
    "views": views.router,
}


class ApiWiringTests(unittest.TestCase):
    def openapi_routes(self):
        spec = main.app.openapi()
        return {(method.upper(), path) for path, ops in spec["paths"].items() for method in ops}

    def test_openapi_schema_builds(self):
        """能生成 OpenAPI 就说明所有请求模型的注解都解析得了。

        from __future__ import annotations 会把注解变成字符串，
        漏 import 的类型（比如 Literal）在导入时不报错，只在这一步暴露。
        """
        spec = main.app.openapi()
        self.assertTrue(spec["paths"])

    def test_every_router_is_mounted(self):
        mounted = self.openapi_routes()
        for name, router in ROUTERS.items():
            declared = {
                (method, route.path)
                for route in router.routes
                for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}
            }
            self.assertTrue(declared, f"{name} 的 router 里一条路由都没有")
            self.assertTrue(
                declared <= mounted,
                f"{name} 的路由没有全部挂上 app：{sorted(declared - mounted)}",
            )

    def test_no_duplicate_routes_across_routers(self):
        seen = {}
        for name, router in ROUTERS.items():
            for route in router.routes:
                for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
                    key = (method, route.path)
                    self.assertNotIn(
                        key, seen,
                        f"{key} 同时由 {seen.get(key)} 和 {name} 提供",
                    )
                    seen[key] = name

    def test_static_frontend_is_still_mounted(self):
        self.assertTrue(
            any(getattr(route, "name", "") == "frontend" for route in main.app.routes),
            "静态前端目录没有挂载，页面会 404",
        )

    def test_compatibility_layer_still_exposes_expected_names(self):
        """main.<名字> 是对外兼容层，删掉任何一个都会打断现有调用方。"""
        for name in [
            "db", "init_db", "build_snapshot", "add_transaction", "restore_backup",
            "set_semester_settings", "archive_habit", "delete_life_goal",
            "TransactionIn", "SemesterSettingsIn", "RestoreSnapshotIn",
            "get_life_overview", "get_life_calendar", "search_life",
        ]:
            self.assertTrue(hasattr(main, name), f"main.{name} 不见了")


if __name__ == "__main__":
    unittest.main()
