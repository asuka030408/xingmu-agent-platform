"""Explicit booking proposal and confirmation HTTP routes."""

from flask import Blueprint, jsonify, request

from . import booking
from .security import audit

booking_routes = Blueprint("booking", __name__)


@booking_routes.post("/api/booking-proposals")
def create_proposal():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "请求必须是 JSON 对象。"}), 400
    try:
        result = booking.proposal(body.get("project_code"), body.get("asset_code"))
        audit("booking_proposal", "created", result["request_key"])
        return jsonify(result)
    except booking.BookingError as exc:
        audit("booking_proposal", "rejected", str(exc))
        return jsonify({"error": str(exc)}), exc.status


@booking_routes.post("/api/bookings/confirm")
def confirm_booking():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "请求必须是 JSON 对象。"}), 400
    try:
        result = booking.confirm(body.get("token"))
        audit("booking_confirm", "idempotent" if result["idempotent"] else "success",
              result["reservation_id"])
        return jsonify(result)
    except booking.BookingError as exc:
        audit("booking_confirm", "rejected", str(exc))
        return jsonify({"error": str(exc)}), exc.status
