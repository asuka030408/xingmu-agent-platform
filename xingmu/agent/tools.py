"""Allowlisted, read-only business tools exposed to the model."""

from dataclasses import dataclass
from datetime import date

from .. import services
from ..jsonutil import ready


@dataclass(frozen=True)
class ToolResult:
    intent: str
    sources: list[str]
    data: object


def _parameters(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "additionalProperties": False}


DATE = {"type": "string", "description": "日期，格式 YYYY-MM-DD；不提供则使用演示项目日期"}
CITY = {"type": "string", "description": "城市，例如上海或杭州；不提供则查询全部城市"}

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "get_delivery_plan",
        "description": "核算待确认项目能否同时交付，返回设备分配、跨仓调拨、替代设备和外租缺口。只读，不会预订。",
        "parameters": _parameters({"day": DATE, "city": CITY,
                                    "project_code": {"type": "string", "description": "具体项目编号，例如 XM-2026-001"}}),
    }},
    {"type": "function", "function": {
        "name": "get_inventory",
        "description": "查询指定日期的设备型号、仓库和可用数量，已扣除正式预订与维修。只读。",
        "parameters": _parameters({"day": DATE, "city": CITY,
                                    "model_code": {"type": "string", "description": "设备型号编号，例如 LED-P3"}}),
    }},
    {"type": "function", "function": {
        "name": "get_maintenance",
        "description": "查询指定日期处于维修时间段的逐台设备及原因。只读。",
        "parameters": _parameters({"day": DATE}),
    }},
    {"type": "function", "function": {
        "name": "list_projects",
        "description": "查询项目名称、编号、城市、状态、活动时间和设备需求数量。只读。",
        "parameters": _parameters({"day": DATE, "city": CITY}),
    }},
    {"type": "function", "function": {
        "name": "get_overview",
        "description": "查询演示日期、仓库数、逐台设备数、待确认项目数和维修设备数。只读。",
        "parameters": _parameters({}),
    }},
]

_ALLOWED_FIELDS = {
    "get_delivery_plan": {"day", "city", "project_code"},
    "get_inventory": {"day", "city", "model_code"},
    "get_maintenance": {"day"},
    "list_projects": {"day", "city"},
    "get_overview": set(),
}


def _text(arguments: dict, name: str, max_length: int = 64) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"参数 {name} 无效")
    return value.strip()


def _day(arguments: dict) -> date | None:
    value = _text(arguments, "day", 10)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期必须是 YYYY-MM-DD") from exc


def execute(name: str, arguments: dict) -> ToolResult:
    """Validate model output before invoking any business function."""
    if name not in _ALLOWED_FIELDS:
        raise ValueError("工具未授权")
    if not isinstance(arguments, dict) or set(arguments) - _ALLOWED_FIELDS[name]:
        raise ValueError("工具参数不符合定义")
    if name == "get_delivery_plan":
        data = services.plan_projects(day=_day(arguments), city=_text(arguments, "city", 30),
                                      project_code=_text(arguments, "project_code", 32))
        return ToolResult("project_plan", ["projects", "requirements", "assets", "reservations",
                                           "maintenance", "substitutions", "transfer_routes"], ready(data))
    if name == "get_inventory":
        rows = services.inventory(_day(arguments))
        city = _text(arguments, "city", 30)
        model = _text(arguments, "model_code", 40)
        if city:
            rows = [row for row in rows if row["warehouse"].startswith(city)]
        if model:
            rows = [row for row in rows if row["code"].lower() == model.lower()]
        return ToolResult("inventory", ["assets", "warehouses", "reservations", "maintenance"], ready(rows))
    if name == "get_maintenance":
        rows = services.maintenance_list(_day(arguments) or services.demo_day())
        return ToolResult("maintenance", ["maintenance", "assets"], ready(rows))
    if name == "list_projects":
        rows = services.projects(day=_day(arguments) or services.demo_day(),
                                 city=_text(arguments, "city", 30))
        return ToolResult("project_list", ["projects", "requirements"], ready(rows))
    return ToolResult("overview", ["projects", "assets", "warehouses", "maintenance"], ready(services.overview()))
