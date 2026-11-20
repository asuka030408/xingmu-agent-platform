from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_ROOT = Path(os.environ.get("XM_POSTGRES_ROOT", r"E:\PostgreSQL-18"))
DATABASE_NAME = "xingmu_equipment"
APP_USER = "xingmu_app"
BOOKING_USER = "xingmu_booking"
APP_PASSWORD_FILE = PROJECT_ROOT / "secrets" / "app-password.txt"
BOOKING_PASSWORD_FILE = PROJECT_ROOT / "secrets" / "booking-password.txt"
APP_SECRET_FILE = PROJECT_ROOT / "secrets" / "flask-secret.txt"
DEEPSEEK_KEY_PATH_FILE = PROJECT_ROOT / "secrets" / "deepseek-key-path.txt"
ADMIN_PASSWORD_FILE = POSTGRES_ROOT / "secrets" / "postgres-password.txt"


def app_password() -> str:
    override = os.environ.get("XM_DB_PASSWORD")
    return override or APP_PASSWORD_FILE.read_text(encoding="ascii").strip()


def admin_password() -> str:
    return ADMIN_PASSWORD_FILE.read_text(encoding="ascii").strip()


def booking_password() -> str:
    return BOOKING_PASSWORD_FILE.read_text(encoding="ascii").strip()


def app_secret() -> str:
    return APP_SECRET_FILE.read_text(encoding="ascii").strip()


def deepseek_api_key() -> str:
    """Read the key from the environment or a local, ignored path pointer."""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    if DEEPSEEK_KEY_PATH_FILE.exists():
        key_path = Path(DEEPSEEK_KEY_PATH_FILE.read_text(encoding="utf-8").strip())
        if key_path.is_file():
            return key_path.read_text(encoding="utf-8").strip()
    return ""
