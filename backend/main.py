"""我的生活中枢 · 后端入口。

[POS] backend/main.py — 建表 + 装配 FastAPI 应用；不含业务计算，也不再定义路由
[INPUT] sqlite3 stdlib · fastapi · pydantic
[OUTPUT] REST API on :8766 + 静态前端服务
[PROTOCOL] 变更接口先改 设计方案.md

分层与依赖方向：

    api/ → views/ → modules/ → core/

- core/    平台通用能力，不认识任何生活模块
- modules/ 各生活模块，保存自己的原始事实，互不调用
- views/   跨模块只读视图，只读取各模块公开的摘要
- api/     HTTP 路由，每个模块一个 APIRouter

新增一个生活模块要做的事：写 modules/<name>.py 并声明 MODULE，
在 modules/__init__.py 的 MODULES 里登记，写 api/<name>.py 并在下面装配。
建表、备份、恢复会自动覆盖到，不需要再改别处。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api import body as body_api
from backend.api import capture as capture_api
from backend.api import categorize as categorize_api
from backend.api import fitness as fitness_api
from backend.api import goals as goals_api
from backend.api import health_import as health_import_api
from backend.api import inbox as inbox_api
from backend.api import insights as insights_api
from backend.api import ledger as ledger_api
from backend.api import nutrition as nutrition_api
from backend.api import platform as platform_api
from backend.api import quick as quick_api
from backend.api import recovery as recovery_api
from backend.api import reflection as reflection_api
from backend.api import rhythm as rhythm_api
from backend.api import statements as statements_api
from backend.api import study as study_api
from backend.api import tags as tags_api
from backend.api import training as training_api
from backend.api import views as views_api
from backend.core import registry
from backend.core.access import TOKEN_HEADER, access_allowed
from backend.core.config import FRONTEND
from backend.core.db import db
from backend.modules import MODULES


def init_db():
    """建好注册表里所有模块的表，再统一跑旧库迁移。"""
    with db() as conn:
        registry.create_schema(conn, MODULES)


init_db()


# ---------- App ----------
app = FastAPI(title="我的生活中枢", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.middleware("http")
async def guard_remote_access(request: Request, call_next):
    """本机照旧放行；其他来源访问 /api/* 必须带 token。

    静态外壳不设门禁：它不含数据，而且 Service Worker 与 manifest
    的请求带不上自定义头。
    """
    if not access_allowed(
        request.client.host if request.client else None,
        request.url.path,
        request.headers.get(TOKEN_HEADER) or request.query_params.get("token"),
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "需要访问令牌。手机端请用启动器给出的带 token 的地址配对。"},
        )
    return await call_next(request)

app.include_router(platform_api.router)
app.include_router(ledger_api.router)
app.include_router(fitness_api.router)
app.include_router(training_api.router)
app.include_router(nutrition_api.router)
app.include_router(recovery_api.router)
app.include_router(body_api.router)
app.include_router(study_api.router)
app.include_router(rhythm_api.router)
app.include_router(reflection_api.router)
app.include_router(goals_api.router)
app.include_router(views_api.router)
app.include_router(capture_api.router)
app.include_router(categorize_api.router)
app.include_router(quick_api.router)
app.include_router(inbox_api.router)
app.include_router(tags_api.router)
app.include_router(insights_api.router)
app.include_router(statements_api.router)
app.include_router(health_import_api.router)


# ---------- Static ----------
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")


# ---------- 兼容层 ----------
# 现有测试与外部调用方按 main.<名字> 访问下面这些函数。
# 它们的真身已经搬进各自的模块，这里只保留入口；改名请连同调用方一起改。
from backend.api.goals import (  # noqa: E402,F401
    delete_life_goal,
)
from backend.api.ledger import (  # noqa: E402,F401
    SemesterSettingsIn,
    TransactionIn,
    add_transaction,
    set_semester_settings,
)
from backend.api.platform import (  # noqa: E402,F401
    RestoreSnapshotIn,
    SettingsIn,
    restore_backup,
)
from backend.api.rhythm import (  # noqa: E402,F401
    archive_habit,
)
from backend.backup import build_snapshot  # noqa: E402,F401
from backend.modules.fitness import (  # noqa: E402,F401
    get_fitness_state,
    record_workout,
)
from backend.modules.goals import (  # noqa: E402,F401
    create_goal_milestone,
    create_life_goal,
    get_life_goals_state,
    set_life_goal_status,
    toggle_goal_milestone,
)
from backend.modules.ledger import (  # noqa: E402,F401
    get_semester,
    get_today_overview,
    parse_quick_entry,
)
from backend.modules.nutrition import (  # noqa: E402,F401
    get_nutrition_state,
    record_meal,
)
from backend.modules.recovery import (  # noqa: E402,F401
    get_recovery_state,
    save_recovery_checkin,
)
from backend.modules.reflection import (  # noqa: E402,F401
    get_reflection_state,
    get_weekly_snapshot,
    save_daily_reflection,
)
from backend.modules.rhythm import (  # noqa: E402,F401
    create_habit,
    create_personal_task,
    get_rhythm_state,
    toggle_habit_checkin,
    toggle_personal_task,
)
from backend.modules.study import (  # noqa: E402,F401
    get_study_state,
    record_study_session,
)
from backend.views.calendar import get_life_calendar  # noqa: E402,F401
from backend.views.overview import get_life_overview  # noqa: E402,F401
from backend.views.search import search_life  # noqa: E402,F401


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8766)
