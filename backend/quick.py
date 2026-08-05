"""全局一句话记录。

手机上唯一合理的交互是一个输入框，所以要能从一句话里认出「这属于哪个模块」。

三条设计原则：

1. **只解析，不写入。** 和账本原有的一句话记账一样，先给出可编辑预览，
   用户确认后才落库。手机上误记一条比漏记一条更难收拾。
2. **含糊就说含糊。** 「午饭 16.5」既可能是一笔支出也可能是一餐热量，
   这时给出主判断的同时列出候选模块，让用户一键改判，而不是替他决定。
3. **认不出就认不出。** 没有把握时返回 matched=False，不硬塞进某个模块。

这里只做文本到意图的推断，不碰数据库写入；真正的落库由 api/quick.py 分发
到各模块自己的写入函数，模块之间仍然互不认识。
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException

from backend.modules.ledger import parse_quick_entry

# 账户与货币信号：出现这些就基本可以确定是在记账
_MONEY_HINTS = (
    "支付宝", "微信", "银行卡", "现金", "校园卡", "饭卡", "花呗", "余额宝",
    "¥", "￥", "元", "块钱", "收入", "到账", "进账", "工资", "生活费", "报销",
)

_ACTIVITY_KEYWORDS = (
    ("cardio", ("跑步", "慢跑", "快走", "有氧", "跳绳", "游泳", "骑行", "单车", "椭圆机")),
    ("strength", ("力量", "举铁", "深蹲", "卧推", "硬拉", "引体", "哑铃", "撸铁", "器械")),
    ("sport", ("篮球", "足球", "羽毛球", "乒乓", "网球", "打球", "爬山", "滑雪")),
    ("mobility", ("拉伸", "瑜伽", "普拉提", "放松", "泡沫轴")),
)
_FITNESS_HINTS = tuple(word for _, words in _ACTIVITY_KEYWORDS for word in words) + ("健身", "训练", "运动")

_MEAL_KEYWORDS = (
    ("breakfast", ("早餐", "早饭")),
    ("lunch", ("午餐", "午饭", "中饭")),
    ("dinner", ("晚餐", "晚饭")),
    ("snack", ("加餐", "零食", "夜宵", "下午茶")),
)
_NUTRITION_HINTS = tuple(word for _, words in _MEAL_KEYWORDS for word in words) + (
    "喝水", "饮水", "喝了", "蛋白", "热量", "千卡", "大卡", "kcal", "毫升",
)

_RECOVERY_HINTS = ("睡了", "睡眠", "睡到", "起床", "精力", "心情", "状态", "小睡", "午睡")
_STUDY_HINTS = ("学习", "看书", "复习", "背单词", "刷题", "上课", "自习", "专注", "写论文", "写作业", "阅读")
_RHYTHM_HINTS = ("待办", "记得", "提醒", "截止", "要交", "之前交", "别忘", "deadline")

MODULE_LABELS = {
    "finance": "个人账本",
    "fitness": "个人健身",
    "nutrition": "个人饮食",
    "recovery": "睡眠与恢复",
    "study": "学习与专注",
    "rhythm": "日程与习惯",
}


def _resolve_date(text: str) -> tuple[str, str, bool]:
    """从文本里剥离日期词，返回（日期, 剩余文本, 是否显式指定）。"""
    working = text
    when = date.today()
    explicit = False
    if "前天" in working:
        when, explicit = date.today() - timedelta(days=2), True
        working = working.replace("前天", " ")
    elif "昨天" in working or "昨晚" in working:
        when, explicit = date.today() - timedelta(days=1), True
        working = working.replace("昨天", " ").replace("昨晚", " ")
    elif "今天" in working:
        explicit = True
        working = working.replace("今天", " ")
    elif "明天" in working:
        when, explicit = date.today() + timedelta(days=1), True
        working = working.replace("明天", " ")
    return when.isoformat(), " ".join(working.split()), explicit


def _first_number(text: str) -> Optional[float]:
    found = re.search(r"(?<![\d.])(\d+(?:\.\d{1,2})?)(?!\d)", text)
    return float(found.group(1)) if found else None


def _duration_minutes(text: str) -> Optional[int]:
    hour = re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|h|H)", text)
    if hour:
        return int(round(float(hour.group(1)) * 60))
    minute = re.search(r"(\d+)\s*(?:分钟|分|min)", text)
    if minute:
        return int(minute.group(1))
    return None


def _scored_intent(text: str) -> list[str]:
    """按优先级返回可能的模块，最可能的在前。"""
    hits = []
    money = any(hint in text for hint in _MONEY_HINTS)
    if money:
        hits.append("finance")
    if any(hint in text for hint in _FITNESS_HINTS):
        hits.append("fitness")
    if any(hint in text for hint in _NUTRITION_HINTS):
        hits.append("nutrition")
    if any(hint in text for hint in _RECOVERY_HINTS):
        hits.append("recovery")
    if any(hint in text for hint in _STUDY_HINTS):
        hits.append("study")
    if any(hint in text for hint in _RHYTHM_HINTS):
        hits.append("rhythm")
    return hits


def _fitness_preview(text: str, when: str) -> dict:
    activity = "other"
    for key, words in _ACTIVITY_KEYWORDS:
        if any(word in text for word in words):
            activity = key
            break
    minutes = _duration_minutes(text)
    intensity = None
    marked = re.search(r"强度\s*(\d{1,2})", text)
    if marked:
        intensity = max(1, min(10, int(marked.group(1))))
    return {
        "occurred_on": when,
        "activity": activity,
        "duration_minutes": minutes,
        "intensity": intensity or 5,
        "note": text,
    }


def _nutrition_preview(text: str, when: str) -> dict:
    meal_type = "snack"
    for key, words in _MEAL_KEYWORDS:
        if any(word in text for word in words):
            meal_type = key
            break
    water = re.search(r"(\d+(?:\.\d+)?)\s*(?:毫升|ml|ML)", text)
    calories = re.search(r"(\d+(?:\.\d+)?)\s*(?:千卡|大卡|kcal|卡)", text)
    protein = re.search(r"蛋白[质]?\s*(\d+(?:\.\d+)?)", text)
    if not water and ("喝水" in text or "饮水" in text):
        cups = _first_number(text)
        water_ml = cups * 1000 if cups and cups <= 5 else cups
    else:
        water_ml = float(water.group(1)) if water else None
    return {
        "occurred_on": when,
        "meal_type": meal_type,
        "name": text,
        "calories": float(calories.group(1)) if calories else None,
        "protein_g": float(protein.group(1)) if protein else None,
        "water_ml": water_ml,
        "note": "",
    }


def _recovery_preview(text: str, when: str) -> dict:
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|h|H)", text)
    energy = re.search(r"精力\s*(\d)", text)
    mood = re.search(r"心情\s*(\d)", text)
    return {
        "occurred_on": when,
        "sleep_hours": float(hours.group(1)) if hours else _first_number(text),
        "sleep_quality": None,
        "energy": int(energy.group(1)) if energy else None,
        "mood": int(mood.group(1)) if mood else None,
        "note": text,
    }


def _study_preview(text: str, when: str) -> dict:
    minutes = _duration_minutes(text)
    focus = re.search(r"专注\s*(\d)", text)
    subject = re.sub(r"\d+\s*(?:小时|分钟|分|h|H|min)", " ", text)
    subject = re.sub(r"(?:学习|看书|复习|刷题|自习|专注)\s*\d*", " ", subject)
    subject = " ".join(subject.split()) or "学习"
    return {
        "occurred_on": when,
        "subject": subject[:30],
        "duration_minutes": minutes,
        "focus": int(focus.group(1)) if focus else 3,
        "note": "",
    }


def _rhythm_preview(text: str, when: str) -> dict:
    title = text
    for word in _RHYTHM_HINTS:
        title = title.replace(word, " ")
    title = " ".join(title.split()) or text
    return {"title": title[:40], "due_on": when, "priority": "normal", "category": "personal", "note": ""}


_PREVIEW_BUILDERS = {
    "fitness": _fitness_preview,
    "nutrition": _nutrition_preview,
    "recovery": _recovery_preview,
    "study": _study_preview,
    "rhythm": _rhythm_preview,
}


def parse_quick_record(conn, raw_text: str) -> dict:
    """把一句话解析成某个模块的待确认预览。只读，不写入任何表。"""
    text = " ".join((raw_text or "").strip().split())
    if not text:
        raise HTTPException(400, "请输入一句话，例如：跑步 30 分钟 强度 6")

    when, stripped, explicit_date = _resolve_date(text)
    candidates = _scored_intent(text)

    if not candidates:
        return {
            "matched": False,
            "input": text,
            "reason": "认不出这句话属于哪个模块，请选一个模块手动填写",
            "alternatives": list(MODULE_LABELS),
        }

    module = candidates[0]
    warnings: list[str] = []

    if module == "finance":
        parsed = parse_quick_entry(conn, text)
        preview = parsed["transaction"]
        confidence = parsed["confidence"]
        warnings.extend(parsed.get("warnings", []))
    else:
        preview = _PREVIEW_BUILDERS[module](stripped, when)
        confidence = 0.6 + (0.2 if explicit_date else 0)
        if module in ("fitness", "study") and not preview.get("duration_minutes"):
            preview["duration_minutes"] = 30
            warnings.append("没有识别到时长，先按 30 分钟填入，请确认")
        if module == "recovery" and preview.get("sleep_hours") is None:
            warnings.append("没有识别到睡眠时长，请补充")
        if module == "rhythm" and not explicit_date:
            warnings.append("没有识别到具体截止日期，先按今天填入，请确认")
        confidence = min(confidence + 0.2 * (len(candidates) == 1), 0.95)

    others = [key for key in candidates[1:]]
    if others:
        warnings.append(
            "这句话也可能属于：" + "、".join(MODULE_LABELS[key] for key in others)
        )

    return {
        "matched": True,
        "input": text,
        "module": module,
        "module_label": MODULE_LABELS[module],
        "confidence": round(confidence, 2),
        "warnings": warnings,
        "preview": preview,
        "alternatives": others or [key for key in MODULE_LABELS if key != module],
    }
