# ADR-0002: 把单文件后端拆成 core / modules / views

## 状态

Accepted

## 背景

ADR-0001 在概念上划清了模块边界，但实现仍然是一个 `backend/main.py`。到第七阶段时它已经 3681 行，
里面同时住着建表语句、十一个模块的业务计算、跨模块视图、Pydantic 模型和全部路由。

每新增一个模块，这个文件就要增加三四百行，而且总览、日历、全局搜索、备份四处都得手工改一遍。
下一阶段要做手机端捕获接口，前端与后端都会再长一截，继续单文件会让新增模块的成本持续上升。

## 决策

按职责把后端拆成四层，`main.py` 只保留建表与应用装配。

```
backend/
  core/      config  db  dates  registry     平台通用能力，不认识任何生活模块
  modules/   ledger  fitness  nutrition  recovery  study  rhythm  goals  reflection
  views/     overview  calendar  search       跨模块只读视图
  api/       每个模块一个 APIRouter
  backup.py  平台级备份，导出范围由模块注册表决定
  main.py    建表 + 装配
```

依赖方向单向：`api` → `views` → `modules` → `core`。模块之间不互相 import；跨模块的汇总一律走 `views`。

每个模块用 `core/registry.py` 里的 `LifeModule` 声明自己拥有哪些表、怎么建、备份导出哪些列、
恢复时按什么顺序清空，并在 `modules/__init__.py` 的 `MODULES` 里登记一次。
建表、备份契约、恢复的写入顺序与清空顺序全部由注册表推导。

数据库位置由 `core/db.py` 独占，通过 `use_database()` 切换。其他地方不得缓存 `DB_PATH`，
否则测试与将来的多宿主部署会读到过期路径。

`main.py` 顶部成批 import 各模块函数，同时充当对外兼容层：现有测试和调用方仍然按 `main.<函数名>` 访问。

## 后果

- `main.py` 从 3681 行降到 149 行；新增模块不再需要往一个巨型文件里塞。
- 新增一个生活模块的动作固定为三步：写 `modules/<name>.py` 并声明 `MODULE`、
  在 `MODULES` 里登记、写 `api/<name>.py` 并装配。建表、备份、恢复自动覆盖到。
- 每个模块的领域不变量现在写在自己文件的 docstring 里，靠近实现而不是只在 CONTEXT.md 里。
- 依赖方向单向，`views` 想改来源数据会立刻表现为反向 import，边界从约定变成了结构约束。
- 代价：多了两层目录，读单个功能要跨文件跳转；`main.py` 末尾的成批 import 是刻意保留的兼容层，
  删掉任何一行都会打断现有调用方，`test_api_wiring` 会守住它。
- 接口、数据库结构和行为完全不变：66 条路由逐条比对一致，函数体逐字未改。

## 保护这套契约的测试

- `tests/test_module_registry.py`：每张表只有一个模块声明所有权；建出来的表与注册表一致；
  备份列与实际列不漂移；写入顺序里父表在子表前；`init_db()` 可重复执行。
- `tests/test_api_wiring.py`：`app.openapi()` 能构建（`from __future__ import annotations`
  会把请求模型的注解变成字符串，漏 import 的类型只在这一步暴露）；每个 router 都挂上了；
  路由不重复；静态目录仍挂载；兼容层的名字还在。

## 考虑过的方案

### 保持单文件，只用注释分区

零风险，但正是当前的状态；分区注释拦不住跨模块的直接调用，边界仍然只是约定。

### 一步到位做插件注册表

目标形态，但需要同时改 schema、备份、路由和四个跨模块视图。先完成纯搬家，让每一步都能用现有测试验证。

## 何时重新审视

- 模块数量继续增长，`main.py` 的路由部分再次变得难以浏览。
- 手机端捕获接口落地后，需要区分「桌面完整接口」与「手机精简接口」。
- 某个模块需要独立开关或独立发布。
