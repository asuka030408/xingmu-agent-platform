"""Add the booking constraint, narrow writer role, and local app secrets.

Safe to rerun. It does not reset business data.
"""

import getpass
from secrets import token_urlsafe
import subprocess

import psycopg
from psycopg import sql

from xingmu.config import (
    ADMIN_PASSWORD_FILE, APP_SECRET_FILE, BOOKING_PASSWORD_FILE,
    BOOKING_USER, DATABASE_NAME, PROJECT_ROOT, admin_password,
)


def ensure_secret(path):
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        path.write_text(token_urlsafe(32), encoding="ascii")
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:F"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Could not restrict permissions on {path.name}: {result.stderr}")
    return path.read_text(encoding="ascii").strip()


def admin_connection(database="postgres", *, autocommit=False):
    return psycopg.connect(
        host="127.0.0.1", port=5432, dbname=database,
        user="postgres", password=admin_password(), autocommit=autocommit,
    )


def migrate():
    if not ADMIN_PASSWORD_FILE.exists():
        raise RuntimeError("PostgreSQL admin password file not found")
    ensure_secret(APP_SECRET_FILE)
    password = ensure_secret(BOOKING_PASSWORD_FILE)
    with admin_connection(autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (BOOKING_USER,)).fetchone()
        command = "ALTER ROLE {} WITH LOGIN PASSWORD {}" if exists else "CREATE ROLE {} WITH LOGIN PASSWORD {}"
        conn.execute(sql.SQL(command).format(sql.Identifier(BOOKING_USER), sql.Literal(password)))
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(DATABASE_NAME), sql.Identifier(BOOKING_USER)
        ))
    with admin_connection(DATABASE_NAME) as conn:
        conn.execute((PROJECT_ROOT / "schema.sql").read_text(encoding="utf-8"))
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(BOOKING_USER)))
        conn.execute(sql.SQL("GRANT SELECT ON projects, assets, warehouses, requirements, substitutions, reservations, maintenance, transfer_routes TO {}").format(sql.Identifier(BOOKING_USER)))
        conn.execute(sql.SQL("GRANT INSERT ON reservations, booking_audit TO {}").format(sql.Identifier(BOOKING_USER)))
        conn.execute(sql.SQL("GRANT USAGE, SELECT ON SEQUENCE reservations_id_seq, booking_audit_id_seq TO {}").format(sql.Identifier(BOOKING_USER)))
        print("Booking constraint, narrow writer role, and local secrets are ready.")


if __name__ == "__main__":
    migrate()
