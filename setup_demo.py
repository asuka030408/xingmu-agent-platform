"""Create the Xingmu demo database and populate it with fictional business data."""

from datetime import datetime, time, timedelta
from pathlib import Path
from secrets import token_urlsafe
import getpass
import subprocess
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql

from xingmu.config import ADMIN_PASSWORD_FILE, APP_USER, DATABASE_NAME, PROJECT_ROOT, admin_password


def admin_connection(database: str = "postgres", *, autocommit: bool = False):
    return psycopg.connect(
        host="127.0.0.1",
        port=5432,
        dbname=database,
        user="postgres",
        password=admin_password(),
        autocommit=autocommit,
    )


def ensure_app_password() -> str:
    path = PROJECT_ROOT / "secrets" / "app-password.txt"
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        path.write_text(token_urlsafe(32), encoding="ascii")
        if subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:F"],
            capture_output=True,
            text=True,
        ).returncode != 0:
            raise RuntimeError("Could not restrict app password file permissions")
    return path.read_text(encoding="ascii").strip()


def ensure_database(password: str) -> None:
    with admin_connection(autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_USER,)).fetchone()
        statement = "ALTER ROLE {} WITH LOGIN PASSWORD {}" if exists else "CREATE ROLE {} WITH LOGIN PASSWORD {}"
        conn.execute(sql.SQL(statement).format(sql.Identifier(APP_USER), sql.Literal(password)))
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE_NAME,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(sql.Identifier(DATABASE_NAME)))
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(DATABASE_NAME), sql.Identifier(APP_USER)
        ))


def next_week_saturday(today):
    offset = (5 - today.weekday()) % 7
    if today.weekday() <= 5:
        offset += 7
    return today + timedelta(days=offset)


def insert_one(conn, query: str, values: tuple) -> int:
    return conn.execute(query + " RETURNING id", values).fetchone()[0]


def seed() -> None:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    demo_day = next_week_saturday(today)
    with admin_connection(DATABASE_NAME) as conn:
        conn.execute((PROJECT_ROOT / "schema.sql").read_text(encoding="utf-8"))
        conn.execute("TRUNCATE booking_audit, company, warehouses, equipment_models, substitutions, assets, projects, requirements, reservations, maintenance, transfer_routes RESTART IDENTITY CASCADE")
        conn.execute(
            "INSERT INTO company(id, name, description) VALUES (1, %s, %s)",
            ("星幕设备", "虚构的演出设备租赁公司；本项目的数据均为演示数据。"),
        )

        warehouses = {}
        for code, name, city in [
            ("SH", "上海浦东仓", "上海"),
            ("HZ", "杭州余杭仓", "杭州"),
        ]:
            warehouses[code] = insert_one(
                conn, "INSERT INTO warehouses(code, name, city) VALUES (%s, %s, %s)",
                (code, name, city),
            )

        models = {}
        for code, name, category, external_cost in [
            ("LED-P3", "P3 LED 屏箱体", "屏幕", 520),
            ("BEAM-230", "230W 摇头灯", "灯光", 360),
            ("BEAM-200", "200W 摇头灯", "灯光", 300),
            ("LINE-ARRAY", "线阵音箱", "音响", 420),
            ("WIRELESS-MIC", "无线话筒", "音响", 130),
        ]:
            models[code] = insert_one(
                conn,
                "INSERT INTO equipment_models(code, name, category, external_rental_cost) VALUES (%s, %s, %s, %s)",
                (code, name, category, external_cost),
            )
        conn.execute(
            "INSERT INTO substitutions(requested_model_id, substitute_model_id, premium_cost) VALUES (%s, %s, %s)",
            (models["BEAM-230"], models["BEAM-200"], 90),
        )

        assets = {}
        quantities = {
            "SH": {"LED-P3": 5, "BEAM-230": 9, "BEAM-200": 3, "LINE-ARRAY": 6, "WIRELESS-MIC": 8},
            "HZ": {"LED-P3": 3, "BEAM-230": 5, "BEAM-200": 2, "LINE-ARRAY": 3, "WIRELESS-MIC": 4},
        }
        for warehouse_code, model_counts in quantities.items():
            for model_code, quantity in model_counts.items():
                for number in range(1, quantity + 1):
                    asset_code = f"{warehouse_code}-{model_code}-{number:02d}"
                    assets[asset_code] = insert_one(
                        conn,
                        "INSERT INTO assets(asset_code, model_id, warehouse_id, status) VALUES (%s, %s, %s, 'active')",
                        (asset_code, models[model_code], warehouses[warehouse_code]),
                    )

        def moment(hour: int, minute: int = 0):
            return datetime.combine(demo_day, time(hour, minute))

        projects = {}
        for code, name, city, venue, status, starts_at, ends_at, priority in [
            ("XM-2026-000", "既有客户年会", "上海", "静安会展中心", "confirmed", moment(8), moment(22), 9),
            ("XM-2026-001", "浦东科技峰会", "上海", "浦东国际会议中心", "draft", moment(9), moment(18), 3),
            ("XM-2026-002", "滨江音乐节", "上海", "徐汇滨江", "draft", moment(14), moment(23), 2),
            ("XM-2026-003", "黄浦品牌发布会", "上海", "黄浦展览馆", "draft", moment(16), moment(21), 1),
        ]:
            projects[code] = insert_one(
                conn,
                "INSERT INTO projects(code, name, city, venue, status, starts_at, ends_at, prep_hours, return_hours, priority) VALUES (%s, %s, %s, %s, %s, %s, %s, 6, 4, %s)",
                (code, name, city, venue, status, starts_at, ends_at, priority),
            )

        demands = {
            "XM-2026-000": {"LED-P3": 1, "BEAM-230": 1, "LINE-ARRAY": 1},
            "XM-2026-001": {"LED-P3": 3, "BEAM-230": 4, "LINE-ARRAY": 2},
            "XM-2026-002": {"LED-P3": 4, "BEAM-230": 8, "LINE-ARRAY": 3},
            "XM-2026-003": {"LED-P3": 2, "BEAM-230": 4, "LINE-ARRAY": 2},
        }
        for project_code, required_models in demands.items():
            for model_code, quantity in required_models.items():
                conn.execute(
                    "INSERT INTO requirements(project_id, model_id, quantity) VALUES (%s, %s, %s)",
                    (projects[project_code], models[model_code], quantity),
                )

        for asset_code in ["SH-LED-P3-01", "SH-BEAM-230-01", "SH-LINE-ARRAY-01"]:
            conn.execute(
                "INSERT INTO reservations(project_id, asset_id, reserved_from, reserved_until) VALUES (%s, %s, %s, %s)",
                (projects["XM-2026-000"], assets[asset_code], moment(2), moment(23) + timedelta(hours=4)),
            )

        for asset_code, reason in [
            ("SH-LED-P3-05", "电源模块故障待修"),
            ("SH-BEAM-230-09", "光源校准与检修"),
        ]:
            conn.execute(
                "INSERT INTO maintenance(asset_id, starts_at, ends_at, reason) VALUES (%s, %s, %s, %s)",
                (assets[asset_code], moment(0) - timedelta(days=1), moment(0) + timedelta(days=2), reason),
            )

        for source, city, hours, cost in [
            ("HZ", "上海", 8, 160),
            ("SH", "杭州", 8, 160),
        ]:
            conn.execute(
                "INSERT INTO transfer_routes(from_warehouse_id, to_city, lead_hours, cost_per_asset) VALUES (%s, %s, %s, %s)",
                (warehouses[source], city, hours, cost),
            )

        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(APP_USER)))
        conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(APP_USER)))
        print(f"Created {DATABASE_NAME} for 星幕设备. Demo event day: {demo_day.isoformat()}")
        print(f"Seeded {len(assets)} serialized assets, {len(projects)} projects, 2 warehouses.")


if __name__ == "__main__":
    if not ADMIN_PASSWORD_FILE.exists():
        raise SystemExit("PostgreSQL admin password file not found; start PostgreSQL first.")
    password = ensure_app_password()
    ensure_database(password)
    seed()
    from migrate_security import migrate
    migrate()
