"""Read-only dashboard and agent HTTP routes."""

from datetime import datetime
import json

from flask import Blueprint, jsonify, request

from . import agent, quality, services
from .config import PROJECT_ROOT
from .jsonutil import ready
from .security import csrf_token

read_routes = Blueprint("read", __name__)


@read_routes.get("/api/session")
def browser_session():
    return jsonify({"csrf_token": csrf_token()})


@read_routes.get("/api/health")
def health():
    return jsonify({"ok": True, "company": "星幕设备", "database": "xingmu_equipment",
                    "demo_day": ready(services.demo_day())})


@read_routes.get("/api/quality")
def data_quality():
    return jsonify(quality.run_checks())


@read_routes.get("/api/overview")
def overview():
    return jsonify(ready(services.overview()))


@read_routes.get("/api/projects")
def projects():
    return jsonify(ready(services.projects()))


@read_routes.get("/api/inventory")
def inventory():
    return jsonify(ready(services.inventory()))


@read_routes.get("/api/maintenance")
def maintenance():
    return jsonify(ready(services.maintenance_list(services.demo_day())))


@read_routes.get("/api/plan")
def plan():
    return jsonify(ready(services.plan_projects(
        city=request.args.get("city") or None,
        project_code=request.args.get("project") or None,
    )))


@read_routes.post("/api/ask")
def ask():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "请求必须是 JSON 对象。"}), 400
    question = body.get("question", "")
    if not isinstance(question, str) or len(question) > 500:
        return jsonify({"error": "问题必须是 500 字以内的文本。"}), 400
    result = agent.ask(question)
    log_file = PROJECT_ROOT / "logs" / "agent-queries.jsonl"
    log_file.parent.mkdir(exist_ok=True)
    with log_file.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"time": datetime.now().isoformat(), "question": question,
                                 "intent": result["intent"]}, ensure_ascii=False) + "\n")
    return jsonify(ready(result))
