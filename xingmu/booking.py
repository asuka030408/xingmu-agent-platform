"""Two-step local booking with signed proposals and database-enforced conflicts."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from psycopg.errors import ExclusionViolation, UniqueViolation

from .config import app_secret
from .db import booking_connection
from . import services


class BookingError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _serializer():
    return URLSafeTimedSerializer(app_secret(), salt="xingmu-booking-proposal-v1")


def proposal(project_code: str, asset_code: str):
    if not isinstance(project_code, str) or not isinstance(asset_code, str):
        raise BookingError("请选择项目和设备。")
    if len(project_code) > 32 or len(asset_code) > 64:
        raise BookingError("项目或设备编号过长。")
    plan = services.plan_projects(project_code=project_code)
    if not plan["projects"]:
        raise BookingError("没有找到可预订的待确认项目。", 404)
    project = plan["projects"][0]
    for requirement in project["requirements"]:
        for assignment in requirement["assignments"]:
            if assignment["asset_code"] == asset_code:
                request_key = str(uuid4())
                payload = {
                    "request_key": request_key,
                    "project_code": project_code,
                    "asset_code": asset_code,
                    "requirement_id": requirement["requirement_id"],
                    "window_start": project["window_start"].isoformat(),
                    "window_end": project["window_end"].isoformat(),
                }
                return {
                    "token": _serializer().dumps(payload),
                    "request_key": request_key,
                    "project_code": project_code,
                    "project_name": project["name"],
                    "asset_code": asset_code,
                    "model_code": assignment["model_code"],
                    "warehouse": assignment["warehouse"],
                    "window_start": payload["window_start"],
                    "window_end": payload["window_end"],
                    "expires_in_seconds": 600,
                }
    raise BookingError("这台设备不在当前项目的可分配方案中，请重新核算。", 409)


def _record_conflict(payload, detail):
    with booking_connection() as conn:
        conn.execute(
            "INSERT INTO booking_audit(request_key, action, outcome, project_code, asset_code, detail) VALUES (%s, 'confirm', 'conflict', %s, %s, %s)",
            (payload["request_key"], payload["project_code"], payload["asset_code"], detail[:200]),
        )


def confirm(token: str):
    if not isinstance(token, str) or len(token) > 4096:
        raise BookingError("预订凭证无效。")
    try:
        payload = _serializer().loads(token, max_age=600)
        request_key = UUID(payload["request_key"])
        project_code = payload["project_code"]
        asset_code = payload["asset_code"]
        requirement_id = int(payload["requirement_id"])
    except SignatureExpired as exc:
        raise BookingError("方案已过期，请重新生成。", 409) from exc
    except (BadSignature, KeyError, TypeError, ValueError) as exc:
        raise BookingError("预订凭证无效。", 400) from exc

    try:
        with booking_connection() as conn:
            with conn.transaction():
                existing = conn.execute(
                    "SELECT r.id, p.code AS project_code, a.asset_code FROM reservations r JOIN projects p ON p.id = r.project_id JOIN assets a ON a.id = r.asset_id WHERE r.request_key = %s",
                    (request_key,),
                ).fetchone()
                if existing:
                    if existing["project_code"] != project_code or existing["asset_code"] != asset_code:
                        raise BookingError("请求编号与原预订不一致。", 409)
                    return {"reservation_id": existing["id"], "project_code": project_code, "asset_code": asset_code, "idempotent": True}

                project = conn.execute(
                    "SELECT id, code, status, city, starts_at, ends_at, prep_hours, return_hours FROM projects WHERE code = %s",
                    (project_code,),
                ).fetchone()
                if not project or project["status"] != "draft":
                    raise BookingError("项目已不存在或不再接受新预订。", 409)
                start = project["starts_at"] - timedelta(hours=project["prep_hours"])
                end = project["ends_at"] + timedelta(hours=project["return_hours"])
                if start.isoformat() != payload["window_start"] or end.isoformat() != payload["window_end"]:
                    raise BookingError("项目时间已改变，请重新生成方案。", 409)

                # Advisory transaction locks serialize bookings without granting UPDATE on business tables.
                conn.execute("SELECT pg_advisory_xact_lock(1, %s)", (requirement_id,))
                requirement = conn.execute(
                    "SELECT id, model_id, quantity FROM requirements WHERE id = %s AND project_id = %s",
                    (requirement_id, project["id"]),
                ).fetchone()
                if not requirement:
                    raise BookingError("设备需求已改变，请重新生成方案。", 409)
                # A concurrent retry of the same token may have waited for this lock.
                existing = conn.execute(
                    "SELECT id FROM reservations WHERE request_key = %s", (request_key,)
                ).fetchone()
                if existing:
                    return {"reservation_id": existing["id"], "project_code": project_code,
                            "asset_code": asset_code, "idempotent": True}
                asset_id_row = conn.execute(
                    "SELECT id FROM assets WHERE asset_code = %s", (asset_code,),
                ).fetchone()
                if not asset_id_row:
                    raise BookingError("设备已不可用。", 409)
                conn.execute("SELECT pg_advisory_xact_lock(2, %s)", (asset_id_row["id"],))
                asset = conn.execute(
                    "SELECT a.id, a.model_id, a.status, w.id AS warehouse_id, w.city AS warehouse_city FROM assets a JOIN warehouses w ON w.id = a.warehouse_id WHERE a.id = %s",
                    (asset_id_row["id"],),
                ).fetchone()
                if not asset or asset["status"] != "active":
                    raise BookingError("设备已不可用。", 409)
                if asset["model_id"] != requirement["model_id"]:
                    substitute = conn.execute(
                        "SELECT 1 FROM substitutions WHERE requested_model_id = %s AND substitute_model_id = %s",
                        (requirement["model_id"], asset["model_id"]),
                    ).fetchone()
                    if not substitute:
                        raise BookingError("设备型号不符合项目需求。", 409)
                count = conn.execute(
                    "SELECT count(*) AS n FROM reservations WHERE project_id = %s AND requirement_id = %s",
                    (project["id"], requirement_id),
                ).fetchone()["n"]
                if count >= requirement["quantity"]:
                    raise BookingError("该型号的项目需求已订满。", 409)
                if conn.execute(
                    "SELECT 1 FROM maintenance WHERE asset_id = %s AND starts_at < %s AND ends_at > %s LIMIT 1",
                    (asset["id"], end, start),
                ).fetchone():
                    raise BookingError("设备在该时间段处于维修状态。", 409)
                if asset["warehouse_city"] != project["city"]:
                    route = conn.execute(
                        "SELECT lead_hours FROM transfer_routes WHERE from_warehouse_id = %s AND to_city = %s",
                        (asset["warehouse_id"], project["city"]),
                    ).fetchone()
                    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
                    if not route or now + timedelta(hours=route["lead_hours"]) > start:
                        raise BookingError("跨仓运输时间不足，请重新核算。", 409)

                row = conn.execute(
                    "INSERT INTO reservations(project_id, asset_id, requirement_id, request_key, reserved_from, reserved_until) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (project["id"], asset["id"], requirement_id, request_key, start, end),
                ).fetchone()
                conn.execute(
                    "INSERT INTO booking_audit(request_key, action, outcome, project_code, asset_code) VALUES (%s, 'confirm', 'success', %s, %s)",
                    (request_key, project_code, asset_code),
                )
                return {"reservation_id": row["id"], "project_code": project_code, "asset_code": asset_code, "idempotent": False}
    except (ExclusionViolation, UniqueViolation) as exc:
        # The database constraint remains the final guard if another process wins.
        _record_conflict(payload, "overlapping reservation or duplicate request")
        raise BookingError("这台设备刚被其他请求预订，请重新核算。", 409) from exc
