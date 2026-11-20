"""Read-only business tools used by the agent and the web API."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .db import connect


def overlaps(first_start, first_end, second_start, second_end) -> bool:
    return first_start < second_end and second_start < first_end


def demo_day():
    with connect() as conn:
        row = conn.execute("SELECT min(starts_at)::date AS day FROM projects WHERE status = 'draft'").fetchone()
        return row["day"]


def projects(day=None, city=None):
    query = """
        SELECT p.id, p.code, p.name, p.city, p.venue, p.status,
               p.starts_at, p.ends_at, p.prep_hours, p.return_hours, p.priority,
               COALESCE(sum(r.quantity), 0)::int AS required_units
        FROM projects p
        LEFT JOIN requirements r ON r.project_id = p.id
        WHERE (%s::date IS NULL OR p.starts_at::date = %s::date)
          AND (%s::text IS NULL OR p.city = %s::text)
        GROUP BY p.id
        ORDER BY p.starts_at, p.priority DESC
    """
    with connect() as conn:
        return conn.execute(query, (day, day, city, city)).fetchall()


def maintenance_list(day=None):
    query = """
        SELECT a.asset_code, m.code AS model_code, m.name AS model_name,
               w.name AS warehouse_name, t.starts_at, t.ends_at, t.reason
        FROM maintenance t
        JOIN assets a ON a.id = t.asset_id
        JOIN equipment_models m ON m.id = a.model_id
        JOIN warehouses w ON w.id = a.warehouse_id
        WHERE (%s::date IS NULL OR (t.starts_at < %s::date + interval '1 day' AND t.ends_at > %s::date))
        ORDER BY t.starts_at, a.asset_code
    """
    with connect() as conn:
        return conn.execute(query, (day, day, day)).fetchall()


def inventory(day=None):
    """Own assets available before allocating draft projects on the given day."""
    day = day or demo_day()
    query = """
        SELECT m.code, m.name, m.category, w.code AS warehouse_code, w.name AS warehouse,
               count(a.id)::int AS total,
               count(a.id) FILTER (
                 WHERE a.status = 'active'
                   AND NOT EXISTS (
                     SELECT 1 FROM maintenance t WHERE t.asset_id = a.id
                       AND t.starts_at < %s::date + interval '1 day' AND t.ends_at > %s::date
                   )
                   AND NOT EXISTS (
                     SELECT 1 FROM reservations r WHERE r.asset_id = a.id
                       AND r.reserved_from < %s::date + interval '1 day' AND r.reserved_until > %s::date
                   )
               )::int AS available
        FROM assets a
        JOIN equipment_models m ON m.id = a.model_id
        JOIN warehouses w ON w.id = a.warehouse_id
        GROUP BY m.code, m.name, m.category, w.code, w.name
        ORDER BY m.category, m.code, w.code
    """
    with connect() as conn:
        return conn.execute(query, (day, day, day, day)).fetchall()


def overview():
    day = demo_day()
    with connect() as conn:
        stats = conn.execute("""
            SELECT
              (SELECT count(*) FROM assets)::int AS assets,
              (SELECT count(*) FROM warehouses)::int AS warehouses,
              (SELECT count(*) FROM projects WHERE status = 'draft' AND starts_at::date = %s)::int AS draft_projects,
              (SELECT count(*) FROM maintenance WHERE starts_at < %s::date + interval '1 day' AND ends_at > %s::date)::int AS maintenance_assets
        """, (day, day, day)).fetchone()
    return {"day": day, **stats}


def _planning_data(day, city, project_code):
    with connect() as conn:
        if project_code:
            target_projects = conn.execute(
                "SELECT * FROM projects WHERE code = %s AND status = 'draft' AND starts_at::date = %s ORDER BY priority DESC, starts_at",
                (project_code, day),
            ).fetchall()
        else:
            target_projects = conn.execute(
                "SELECT * FROM projects WHERE status = 'draft' AND starts_at::date = %s AND (%s::text IS NULL OR city = %s::text) ORDER BY priority DESC, starts_at",
                (day, city, city),
            ).fetchall()
        if not target_projects:
            return None
        project_ids = [p["id"] for p in target_projects]
        requirements = conn.execute(
            "SELECT r.id AS requirement_id, r.project_id, r.model_id, r.quantity, m.code AS model_code, m.name AS model_name, m.external_rental_cost FROM requirements r JOIN equipment_models m ON m.id = r.model_id WHERE r.project_id = ANY(%s) ORDER BY r.project_id, m.code",
            (project_ids,),
        ).fetchall()
        assets = conn.execute(
            "SELECT a.id, a.asset_code, a.model_id, a.status, a.warehouse_id, w.code AS warehouse_code, w.name AS warehouse_name, w.city AS warehouse_city, m.code AS model_code FROM assets a JOIN warehouses w ON w.id = a.warehouse_id JOIN equipment_models m ON m.id = a.model_id ORDER BY a.asset_code"
        ).fetchall()
        reservations = conn.execute(
            "SELECT asset_id, reserved_from, reserved_until FROM reservations"
        ).fetchall()
        maintenance = conn.execute(
            "SELECT asset_id, starts_at, ends_at FROM maintenance"
        ).fetchall()
        substitutions = conn.execute(
            "SELECT requested_model_id, substitute_model_id, premium_cost FROM substitutions"
        ).fetchall()
        routes = conn.execute(
            "SELECT from_warehouse_id, to_city, lead_hours, cost_per_asset FROM transfer_routes"
        ).fetchall()
    return target_projects, requirements, assets, reservations, maintenance, substitutions, routes


def plan_projects(day=None, city=None, project_code=None, now=None):
    """Greedy low-cost allocation; external rental is a recommendation, not a booking."""
    day = day or demo_day()
    data = _planning_data(day, city, project_code)
    if data is None:
        return {"day": day, "projects": [], "external_units": 0, "estimated_extra_cost": 0}
    target_projects, requirements, assets, reservations, maintenance, substitutions, routes = data
    substitutions_by_model = {}
    for item in substitutions:
        substitutions_by_model.setdefault(item["requested_model_id"], {})[item["substitute_model_id"]] = item["premium_cost"]
    routes_by_warehouse_city = {(r["from_warehouse_id"], r["to_city"]): r for r in routes}
    requirements_by_project = {}
    for requirement in requirements:
        requirements_by_project.setdefault(requirement["project_id"], []).append(requirement)
    confirmed_blocks = {}
    for row in reservations:
        confirmed_blocks.setdefault(row["asset_id"], []).append((row["reserved_from"], row["reserved_until"]))
    repair_blocks = {}
    for row in maintenance:
        repair_blocks.setdefault(row["asset_id"], []).append((row["starts_at"], row["ends_at"]))
    assigned_blocks = {}
    now = now or datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)

    results = []
    for project in target_projects:
        window_start = project["starts_at"] - timedelta(hours=project["prep_hours"])
        window_end = project["ends_at"] + timedelta(hours=project["return_hours"])
        result = {
            "code": project["code"], "name": project["name"], "city": project["city"],
            "venue": project["venue"], "starts_at": project["starts_at"],
            "ends_at": project["ends_at"], "window_start": window_start,
            "window_end": window_end, "priority": project["priority"],
            "requirements": [], "external_units": 0, "transfer_units": 0,
            "substitute_units": 0, "estimated_extra_cost": 0,
        }
        for requirement in requirements_by_project.get(project["id"], []):
            choices = []
            allowed_substitutes = substitutions_by_model.get(requirement["model_id"], {})
            for asset in assets:
                if asset["status"] != "active":
                    continue
                if asset["model_id"] != requirement["model_id"] and asset["model_id"] not in allowed_substitutes:
                    continue
                blocked = confirmed_blocks.get(asset["id"], []) + repair_blocks.get(asset["id"], []) + assigned_blocks.get(asset["id"], [])
                if any(overlaps(window_start, window_end, start, end) for start, end in blocked):
                    continue
                is_remote = asset["warehouse_city"] != project["city"]
                route = routes_by_warehouse_city.get((asset["warehouse_id"], project["city"])) if is_remote else None
                if is_remote and (route is None or now + timedelta(hours=route["lead_hours"]) > window_start):
                    continue
                is_substitute = asset["model_id"] != requirement["model_id"]
                cost = (route["cost_per_asset"] if route else 0) + (allowed_substitutes[asset["model_id"]] if is_substitute else 0)
                choices.append((cost, asset["asset_code"], asset, is_remote, is_substitute))
            choices.sort(key=lambda choice: (choice[0], choice[1]))
            selected = choices[:requirement["quantity"]]
            assignments = []
            for cost, _, asset, is_remote, is_substitute in selected:
                assigned_blocks.setdefault(asset["id"], []).append((window_start, window_end))
                assignments.append({
                    "asset_code": asset["asset_code"], "model_code": asset["model_code"],
                    "warehouse": asset["warehouse_name"], "transfer": is_remote,
                    "substitute": is_substitute, "cost": cost,
                })
                result["transfer_units"] += int(is_remote)
                result["substitute_units"] += int(is_substitute)
                result["estimated_extra_cost"] += cost
            external_needed = requirement["quantity"] - len(selected)
            result["external_units"] += external_needed
            result["estimated_extra_cost"] += external_needed * requirement["external_rental_cost"]
            result["requirements"].append({
                "requirement_id": requirement["requirement_id"],
                "model_code": requirement["model_code"], "model_name": requirement["model_name"],
                "quantity": requirement["quantity"], "assignments": assignments,
                "external_needed": external_needed,
                "external_cost_per_unit": requirement["external_rental_cost"],
            })
        result["status"] = "可用自有设备交付" if result["external_units"] == 0 else "需外租确认"
        results.append(result)
    return {
        "day": day, "projects": results,
        "external_units": sum(project["external_units"] for project in results),
        "transfer_units": sum(project["transfer_units"] for project in results),
        "substitute_units": sum(project["substitute_units"] for project in results),
        "estimated_extra_cost": sum(project["estimated_extra_cost"] for project in results),
    }
