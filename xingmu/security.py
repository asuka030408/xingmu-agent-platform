"""Local browser boundary, CSRF checks, request limits, and audit log."""

from collections import defaultdict, deque
from datetime import datetime, timezone
import json
from secrets import compare_digest, token_urlsafe
from threading import Lock
from time import monotonic

from flask import jsonify, request, session

from .config import PROJECT_ROOT, app_secret

_lock = Lock()
_requests = defaultdict(deque)
_audit_lock = Lock()


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = token_urlsafe(32)
    return session["csrf"]


def audit(event, outcome, detail=""):
    record = {"time": datetime.now(timezone.utc).isoformat(), "event": event,
              "outcome": outcome, "detail": str(detail)[:200]}
    path = PROJECT_ROOT / "logs" / "security.jsonl"
    path.parent.mkdir(exist_ok=True)
    with _audit_lock, path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")


def _limited():
    now = monotonic()
    if request.path.startswith("/api/booking"):
        category, limit = "booking", 30
    elif request.path == "/api/ask":
        category, limit = "agent", 20
    else:
        category, limit = "read", 120
    key = (request.remote_addr or "local", category)
    with _lock:
        bucket = _requests[key]
        while bucket and bucket[0] <= now - 60:
            bucket.popleft()
        if len(bucket) >= limit:
            return True
        bucket.append(now)
        return False


def init_security(app):
    app.secret_key = app_secret()
    app.config.update(
        MAX_CONTENT_LENGTH=16 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        TRUSTED_HOSTS=["127.0.0.1", "localhost"],
    )

    @app.before_request
    def protect_request():
        if not request.path.startswith("/api/"):
            return None
        if _limited():
            audit(request.path, "rate_limited")
            return jsonify({"error": "请求过于频繁，请稍后重试。"}), 429
        if request.method != "POST":
            return None
        origin = request.headers.get("Origin")
        if origin and origin not in ("http://127.0.0.1:8765", "http://localhost:8765"):
            audit(request.path, "rejected_origin")
            return jsonify({"error": "请求来源不被允许。"}), 403
        supplied = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf", "")
        if not expected or not compare_digest(supplied, expected):
            audit(request.path, "rejected_csrf")
            return jsonify({"error": "会话校验失败，请刷新页面重试。"}), 403
        if not request.is_json:
            return jsonify({"error": "请发送 JSON 请求。"}), 415
        return None

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response
