"""Small, explicit data checks for the demo catalog."""

from .db import connect


def run_checks():
    checks = []
    with connect() as conn:
        queries = [
            ("项目必须有设备需求", "SELECT count(*) FROM projects p WHERE NOT EXISTS (SELECT 1 FROM requirements r WHERE r.project_id = p.id)"),
            ("确认预订不能重复占用同一设备", """
                SELECT count(*) FROM reservations a JOIN reservations b
                  ON a.asset_id = b.asset_id AND a.id < b.id
                 AND a.reserved_from < b.reserved_until AND b.reserved_from < a.reserved_until
            """),
            ("确认预订不能与维修重叠", """
                SELECT count(*) FROM reservations r JOIN maintenance m ON r.asset_id = m.asset_id
                 AND r.reserved_from < m.ends_at AND m.starts_at < r.reserved_until
            """),
            ("设备必须关联仓库和型号", """
                SELECT count(*) FROM assets a
                LEFT JOIN warehouses w ON w.id = a.warehouse_id
                LEFT JOIN equipment_models m ON m.id = a.model_id
                WHERE w.id IS NULL OR m.id IS NULL
            """),
        ]
        for name, query in queries:
            failures = conn.execute(query).fetchone()["count"]
            checks.append({"name": name, "passed": failures == 0, "failures": failures})
    return {"passed": all(item["passed"] for item in checks), "checks": checks}
