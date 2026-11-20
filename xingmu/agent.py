"""A transparent offline agent: intent routing plus approved business tools.

It works without an API key. It does not generate arbitrary SQL or change bookings.
"""

from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

from . import services


EXAMPLES = [
    "下周六上海的三个活动能同时交付吗？",
    "浦东科技峰会缺什么设备？",
    "上海仓的 LED-P3 还有多少可用？",
    "哪些设备正在维修？",
    "下周六有哪些项目？",
]


def _question_day(question):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    match = re.search(r"(20\d{2})[-/]([01]?\d)[-/]([0-3]?\d)", question)
    if match:
        try:
            return today.replace(year=int(match[1]), month=int(match[2]), day=int(match[3]))
        except ValueError:
            return None
    match = re.search(r"([01]?\d)月([0-3]?\d)日?", question)
    if match:
        try:
            return today.replace(month=int(match[1]), day=int(match[2]))
        except ValueError:
            return None
    if "明天" in question:
        return today + timedelta(days=1)
    if "今天" in question:
        return today
    if "下周六" in question:
        offset = (5 - today.weekday()) % 7
        if today.weekday() <= 5:
            offset += 7
        return today + timedelta(days=offset)
    return services.demo_day()


def _project_from_question(question):
    match = re.search(r"XM-\d{4}-\d{3}", question, re.IGNORECASE)
    if match:
        return match.group().upper()
    for project in services.projects():
        if project["name"] in question:
            return project["code"]
    return None


def _answer_plan(question, day):
    city = "上海" if "上海" in question else "杭州" if "杭州" in question else None
    project_code = _project_from_question(question)
    plan = services.plan_projects(day=day, city=city, project_code=project_code)
    if not plan["projects"]:
        return {
            "intent": "project_plan", "answer": f"{day} 没有找到匹配的待确认项目。可以问‘下周六有哪些项目？’。",
            "sources": ["projects"], "data": plan,
        }
    lines = [f"{plan['day']} 共核算 {len(plan['projects'])} 个待确认项目。"]
    if plan["external_units"]:
        lines.append(f"自有设备不足以全部同时交付：建议跨仓调拨 {plan['transfer_units']} 件、使用可替代设备 {plan['substitute_units']} 件，另有 {plan['external_units']} 件需外租确认。")
    else:
        lines.append(f"自有设备可以覆盖全部需求，其中跨仓调拨 {plan['transfer_units']} 件、使用可替代设备 {plan['substitute_units']} 件。")
    for project in plan["projects"]:
        shortages = [f"{item['model_name']} {item['external_needed']} 件" for item in project["requirements"] if item["external_needed"]]
        detail = "；外租缺口：" + "、".join(shortages) if shortages else "；无外租缺口"
        lines.append(f"{project['name']}（{project['code']}）：{project['status']}{detail}。")
    lines.append(f"调拨、替代及外租的估算增量成本合计 ¥{plan['estimated_extra_cost']:,}。外租价格为演示数据，需由调度员向供应商确认；方案尚未写入订单。")
    lines.append("核算占用时间包含备货、活动和归还检查，且扣除了已确认预订和维修设备。")
    return {
        "intent": "project_plan", "answer": "\n".join(lines),
        "sources": ["projects", "requirements", "assets", "reservations", "maintenance", "substitutions", "transfer_routes"],
        "data": plan,
    }


def _answer_inventory(question, day):
    rows = services.inventory(day)
    matched = [row for row in rows if row["code"].lower() in question.lower() or row["name"] in question]
    if not matched:
        matched = rows
    if "上海" in question:
        matched = [row for row in matched if row["warehouse_code"] == "SH"]
    elif "杭州" in question:
        matched = [row for row in matched if row["warehouse_code"] == "HZ"]
    if not matched:
        text = "没有找到匹配的设备型号或仓库。"
    else:
        text = f"{day} 已扣除已确认预订和维修后的自有设备：\n" + "\n".join(
            f"{row['warehouse']} · {row['name']}（{row['code']}）：{row['available']}/{row['total']} 件可用"
            for row in matched
        )
        text += "\n待确认项目尚未占用这些数量；要核算多个项目，请问‘下周六三个活动能同时交付吗？’。"
    return {"intent": "inventory", "answer": text, "sources": ["assets", "warehouses", "reservations", "maintenance"], "data": matched}


def _answer_maintenance(day):
    rows = services.maintenance_list(day)
    if not rows:
        text = f"{day} 没有设备处于维修时间段。"
    else:
        text = f"{day} 有 {len(rows)} 台设备处于维修时间段：\n" + "\n".join(
            f"{row['asset_code']}（{row['model_name']}，{row['warehouse_name']}）：{row['reason']}"
            for row in rows
        )
    return {"intent": "maintenance", "answer": text, "sources": ["maintenance", "assets"], "data": rows}


def _answer_projects(day):
    rows = services.projects(day)
    if rows:
        text = f"{day} 的项目：\n" + "\n".join(
            f"{row['code']} · {row['name']} · {row['city']} · {row['status']} · 需求 {row['required_units']} 件"
            for row in rows
        )
    else:
        text = f"{day} 没有项目记录。"
    return {"intent": "project_list", "answer": text, "sources": ["projects", "requirements"], "data": rows}


def ask(question: str):
    question = question.strip()
    if not question:
        return {"intent": "help", "answer": "请输入问题，例如：" + "；".join(EXAMPLES), "sources": [], "data": None}
    day = _question_day(question)
    if day is None:
        return {"intent": "help", "answer": "日期格式无效，请使用 2026-11-28 这样的日期。", "sources": [], "data": None}
    if "维修" in question and not any(word in question for word in ("项目", "交付", "活动", "缺口")):
        return _answer_maintenance(day)
    if any(word in question for word in ("库存", "可用", "还剩", "有多少")) and not any(word in question for word in ("项目", "交付", "活动")):
        return _answer_inventory(question, day)
    if any(word in question for word in ("哪些项目", "什么项目", "项目列表", "有哪些活动")):
        return _answer_projects(day)
    if _project_from_question(question) or any(word in question for word in ("交付", "调拨", "缺口", "冲突", "活动", "方案", "项目")):
        return _answer_plan(question, day)
    return {"intent": "help", "answer": "目前可查询项目交付、设备库存和维修信息。试试：" + "；".join(EXAMPLES), "sources": [], "data": None}
