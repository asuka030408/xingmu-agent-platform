from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from threading import Lock
import atexit

from .config import APP_USER, BOOKING_USER, DATABASE_NAME, app_password, booking_password

_lock = Lock()
_read_pool = None
_write_pool = None


def _pool(write=False):
    global _read_pool, _write_pool
    with _lock:
        current = _write_pool if write else _read_pool
        if current is None:
            current = ConnectionPool(
                kwargs={
                    "host": "127.0.0.1", "port": 5432, "dbname": DATABASE_NAME,
                    "user": BOOKING_USER if write else APP_USER,
                    "password": booking_password() if write else app_password(),
                    "row_factory": dict_row, "connect_timeout": 5,
                    "options": "-c statement_timeout=8000 -c lock_timeout=5000",
                },
                min_size=1, max_size=4 if write else 8, timeout=5,
                max_waiting=20, open=True,
            )
            if write:
                _write_pool = current
            else:
                _read_pool = current
        return current


def connect():
    """Read-only database connection for the agent and dashboards."""
    return _pool().connection()


def booking_connection():
    """Narrow writer connection, used only by the booking module."""
    return _pool(write=True).connection()


def close_pools():
    for pool in (_read_pool, _write_pool):
        if pool is not None:
            pool.close()


atexit.register(close_pools)
