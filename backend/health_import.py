"""从运动手环 / 健康 App 的导出文件补录训练与体重。

为什么是导出文件而不是 API：

- 华为 Health Kit 之类的官方接口要注册应用、过审核，而且数据要绕一圈云端，
  与「数据只在本机」的前提冲突；
- Health Connect 只有原生安卓应用能读，我们手机端是 PWA，读不了。

所以走和月度账单同一条路：解析导出文件 → 和已有记录对账 → 只补没记过的 → 确认后写入。
不依赖任何审核，也不经过第三方服务器。

**列名映射按常见导出格式编写，没有对着真实导出文件验证过。**
拿到真文件后应当先跑预览，确认条数与数值，必要时补一条映射规则。
认不出的行不猜，放进 skipped 让用户自己看。
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Iterable, Optional

from fastapi import HTTPException

KINDS = {
    "workout": "训练记录",
    "body": "身体指标",
}

# 一列可能出现的多种叫法。加一种写法只要往这里补。
_DATE_COLUMNS = ("日期", "date", "开始时间", "运动时间", "startTime", "时间", "测量时间")
_DURATION_COLUMNS = ("时长", "运动时长", "duration", "durationMinutes", "锻炼时长(分钟)")
_TYPE_COLUMNS = ("运动类型", "类型", "type", "exerciseType", "运动项目")
_DISTANCE_COLUMNS = ("距离", "distance", "距离(km)", "距离(公里)")
_CALORIE_COLUMNS = ("消耗", "卡路里", "calories", "热量(千卡)")
_WEIGHT_COLUMNS = ("体重", "weight", "体重(kg)", "weightKg")
_FAT_COLUMNS = ("体脂率", "体脂", "bodyFat", "体脂率(%)")

# 导出文件里的运动名 -> 平台的活动分类
_ACTIVITY_MAP = (
    ("cardio", ("跑步", "户外跑", "室内跑", "健走", "快走", "骑行", "单车", "游泳",
                "椭圆机", "划船机", "跳绳", "run", "walk", "cycl", "swim")),
    ("strength", ("力量", "健身", "器械", "自由训练", "strength", "weight")),
    ("sport", ("篮球", "足球", "羽毛球", "网球", "乒乓", "爬山", "登山", "滑雪")),
    ("mobility", ("拉伸", "瑜伽", "普拉提", "yoga", "stretch")),
)


def _pick(row: dict, names: Iterable[str]) -> str:
    for key, value in row.items():
        clean_key = (key or "").strip()
        for name in names:
            if clean_key == name or name in clean_key:
                text = (value or "").strip()
                if text:
                    return text
    return ""


def _parse_day(raw: str) -> Optional[str]:
    found = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", raw or "")
    if not found:
        return None
    try:
        return date(int(found.group(1)), int(found.group(2)), int(found.group(3))).isoformat()
    except ValueError:
        return None


def _parse_number(raw: str) -> Optional[float]:
    found = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)", (raw or "").replace(",", ""))
    return float(found.group(1)) if found else None


def _parse_minutes(raw: str) -> Optional[int]:
    """时长可能写成 45、45分钟、00:45:00 或 1小时20分。"""
    text = (raw or "").strip()
    if not text:
        return None
    clock = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", text)
    if clock:
        hours, minutes = int(clock.group(1)), int(clock.group(2))
        # 两段式按 时:分 读，三段式按 时:分:秒 读
        if clock.group(3) is None:
            return hours * 60 + minutes
        return hours * 60 + minutes + (1 if int(clock.group(3)) >= 30 else 0)
    hour_part = re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|h)", text)
    minute_part = re.search(r"(\d+(?:\.\d+)?)\s*(?:分钟|分|min)", text)
    if hour_part or minute_part:
        total = (float(hour_part.group(1)) * 60 if hour_part else 0)
        total += float(minute_part.group(1)) if minute_part else 0
        return int(round(total)) or None
    plain = _parse_number(text)
    return int(round(plain)) if plain else None


def _guess_activity(raw: str) -> str:
    lowered = (raw or "").lower()
    for key, words in _ACTIVITY_MAP:
        if any(word.lower() in lowered for word in words):
            return key
    return "other"


def _read_rows(text: str) -> list[dict]:
    if not (text or "").strip():
        raise HTTPException(400, "导出文件内容为空")
    rows = list(csv.reader(io.StringIO(text)))
    header_index = None
    for index, row in enumerate(rows):
        cells = [(cell or "").strip() for cell in row]
        if any(any(name in cell for name in _DATE_COLUMNS) for cell in cells if cell):
            header_index = index
            break
    if header_index is None:
        raise HTTPException(400, "找不到表头。请确认导出的是明细 CSV，且含日期列")
    header = [(cell or "").strip() for cell in rows[header_index]]
    parsed = []
    for line_number, raw_row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any((cell or "").strip() for cell in raw_row):
            continue
        parsed.append((line_number, {
            header[i]: (raw_row[i] if i < len(raw_row) else "") for i in range(len(header))
        }))
    return parsed


def parse_health_export(text: str, kind: str) -> dict:
    """把导出文件解析成统一的行。只读，不碰数据库。"""
    if kind not in KINDS:
        raise HTTPException(400, f"未知的导入类型：{kind}")

    parsed: list[dict] = []
    skipped: list[dict] = []
    for line_number, row in _read_rows(text):
        occurred_on = _parse_day(_pick(row, _DATE_COLUMNS))
        if not occurred_on:
            skipped.append({"line": line_number, "reason": "认不出日期"})
            continue

        if kind == "workout":
            minutes = _parse_minutes(_pick(row, _DURATION_COLUMNS))
            if not minutes or minutes <= 0:
                skipped.append({"line": line_number, "reason": "认不出运动时长"})
                continue
            raw_type = _pick(row, _TYPE_COLUMNS)
            parsed.append({
                "occurred_on": occurred_on,
                "activity": _guess_activity(raw_type),
                "duration_minutes": min(minutes, 1440),
                "distance_km": _parse_number(_pick(row, _DISTANCE_COLUMNS)),
                "calories": _parse_number(_pick(row, _CALORIE_COLUMNS)),
                "note": (raw_type or "导入的运动记录")[:120],
                "line": line_number,
            })
        else:
            weight = _parse_number(_pick(row, _WEIGHT_COLUMNS))
            body_fat = _parse_number(_pick(row, _FAT_COLUMNS))
            if weight is None and body_fat is None:
                skipped.append({"line": line_number, "reason": "既没有体重也没有体脂"})
                continue
            parsed.append({
                "occurred_on": occurred_on,
                "weight_kg": weight,
                "body_fat_pct": body_fat,
                "line": line_number,
            })

    return {
        "kind": kind,
        "kind_label": KINDS[kind],
        "rows": parsed,
        "skipped": skipped,
        "summary": {
            "parsed": len(parsed),
            "skipped": len(skipped),
            "date_from": min((r["occurred_on"] for r in parsed), default=None),
            "date_to": max((r["occurred_on"] for r in parsed), default=None),
        },
    }


def reconcile_health(conn, rows: list[dict], kind: str) -> dict:
    """和已有记录对账。

    训练按「同一天 + 时长相同」认领，一条已有记录只能被认领一次；
    身体指标按天认领，因为每天至多一条。

    对不上只表示本地没有匹配的记录，不代表这次运动没发生过。
    """
    if not rows:
        return {"new": [], "matched": [], "summary": {"new": 0, "matched": 0}}

    days = sorted({row["occurred_on"] for row in rows})
    new_rows: list[dict] = []
    matched: list[dict] = []

    if kind == "workout":
        pool: dict[tuple, list[int]] = {}
        for record in conn.execute(
            """SELECT id, occurred_on, duration_minutes FROM fitness_sessions
               WHERE occurred_on BETWEEN ? AND ?""",
            (days[0], days[-1]),
        ).fetchall():
            pool.setdefault(
                (record["occurred_on"], int(record["duration_minutes"])), []
            ).append(record["id"])
        for row in rows:
            key = (row["occurred_on"], int(row["duration_minutes"]))
            bucket = pool.get(key)
            if bucket:
                matched.append({**row, "session_id": bucket.pop(0)})
            else:
                new_rows.append(row)
    else:
        existing = {
            record["occurred_on"]
            for record in conn.execute(
                "SELECT occurred_on FROM body_measurements WHERE occurred_on BETWEEN ? AND ?",
                (days[0], days[-1]),
            ).fetchall()
        }
        for row in rows:
            if row["occurred_on"] in existing:
                matched.append(row)
            else:
                new_rows.append(row)

    return {
        "new": new_rows,
        "matched": matched,
        "summary": {
            "new": len(new_rows),
            "matched": len(matched),
            "date_from": days[0],
            "date_to": days[-1],
        },
    }


def build_health_preview(conn, text: str, kind: str) -> dict:
    """解析 + 对账，一次给出可确认的预览。全程只读。"""
    parsed = parse_health_export(text, kind)
    result = reconcile_health(conn, parsed["rows"], kind)
    return {
        **parsed,
        "reconciliation": result,
        "generated_at": datetime.now().isoformat(),
        "note": (
            "只有「还没记」的行会写入。已经记过的不会重复导入；"
            "身体指标同一天已有记录时不会被覆盖，需要改就到那天手动改。"
        ),
    }
