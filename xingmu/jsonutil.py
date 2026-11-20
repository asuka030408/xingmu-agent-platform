"""Small JSON conversion helper for database date values."""

from datetime import date, datetime


def ready(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [ready(item) for item in value]
    if isinstance(value, dict):
        return {key: ready(item) for key, item in value.items()}
    return value
