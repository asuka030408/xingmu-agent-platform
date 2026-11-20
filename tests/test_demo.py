import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from xingmu import agent, booking, quality, security, services
from xingmu.agent import tools as agent_tools
from xingmu.agent.errors import AgentError
from xingmu.app import app
from xingmu.db import booking_connection, connect
from migrate_security import admin_connection


class XingmuDemoTests(unittest.TestCase):
    def test_seed_and_business_counts(self):
        data = services.overview()
        self.assertEqual(data["assets"], 48)
        self.assertEqual(data["warehouses"], 2)
        self.assertEqual(data["draft_projects"], 3)
        self.assertEqual(data["maintenance_assets"], 2)

    def test_simultaneous_plan_respects_asset_blocks(self):
        plan = services.plan_projects(city="上海")
        self.assertEqual(len(plan["projects"]), 3)
        self.assertEqual(plan["external_units"], 3)
        used_codes = [assignment["asset_code"] for project in plan["projects"]
                      for requirement in project["requirements"]
                      for assignment in requirement["assignments"]]
        self.assertEqual(len(used_codes), len(set(used_codes)))
        self.assertNotIn("SH-LED-P3-01", used_codes)  # confirmed project
        self.assertNotIn("SH-LED-P3-05", used_codes)  # maintenance
        self.assertNotIn("SH-BEAM-230-09", used_codes)  # maintenance

    def test_explicit_wrong_date_does_not_plan_seeded_project(self):
        day = services.demo_day() + timedelta(days=1)
        self.assertEqual(services.plan_projects(day=day, project_code="XM-2026-001")["projects"], [])

    def test_agent_and_api(self):
        def model(messages, tool_specs, tool_choice):
            if tool_choice == "required":
                return ({"content": None, "tool_calls": [{"id": "call_1", "type": "function",
                        "function": {"name": "get_maintenance", "arguments": "{}"}}]}, "tool_calls")
            self.assertEqual(messages[-1]["role"], "tool")
            return ({"content": "演示日期有两台设备处于维修时间段。"}, "stop")

        client = app.test_client()
        self.assertEqual(client.get("/api/health").status_code, 200)
        token = client.get("/api/session").json["csrf_token"]
        with patch("xingmu.agent.runtime.deepseek.complete", side_effect=model):
            response = client.post("/api/ask", json={"question": "哪些设备正在维修？"},
                                   headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["intent"], "maintenance")
        self.assertEqual(response.json["tools_used"], ["get_maintenance"])
        self.assertTrue(client.get("/api/quality").json["passed"])

    def test_agent_model_selects_plan_tool(self):
        def model(messages, tool_specs, tool_choice):
            if tool_choice == "required":
                self.assertTrue(any(tool["function"]["name"] == "get_delivery_plan" for tool in tool_specs))
                return ({"content": None, "tool_calls": [{"id": "call_plan", "type": "function",
                        "function": {"name": "get_delivery_plan", "arguments": '{"city":"上海"}'}}]}, "tool_calls")
            self.assertIn('"external_units": 3', messages[-1]["content"])
            return ({"content": "上海三个项目同时交付还需外租三件设备。"}, "stop")

        with patch("xingmu.agent.runtime.deepseek.complete", side_effect=model):
            reply = agent.ask("下周六上海的三个活动能同时交付吗？")
        self.assertEqual(reply["intent"], "project_plan")
        self.assertEqual(reply["data"]["external_units"], 3)
        self.assertEqual(reply["tools_used"], ["get_delivery_plan"])

    def test_agent_rejects_unlisted_tools_and_unverified_answers(self):
        with self.assertRaises(ValueError):
            agent_tools.execute("execute_sql", {"sql": "DELETE FROM assets"})
        with patch("xingmu.agent.runtime.deepseek.complete",
                   return_value=({"content": "没有查库也能回答。"}, "stop")):
            with self.assertRaises(AgentError):
                agent.ask("上海有多少设备？")

    def test_agent_without_key_does_not_use_rule_fallback(self):
        with patch("xingmu.agent.deepseek.deepseek_api_key", return_value=""):
            with self.assertRaises(AgentError) as context:
                agent.ask("上海库存有多少？")
        self.assertEqual(context.exception.status, 503)

    def test_data_quality(self):
        self.assertTrue(quality.run_checks()["passed"])

    def test_web_role_is_read_only(self):
        with connect() as conn:
            with self.assertRaises(Exception):
                conn.execute("CREATE TABLE forbidden_test(id integer)")

    def test_browser_boundary(self):
        client = app.test_client()
        self.assertEqual(client.post("/api/ask", json={"question": "库存"}).status_code, 403)
        token = client.get("/api/session").json["csrf_token"]
        self.assertEqual(client.post("/api/ask", json={"question": "库存"},
                                     headers={"X-CSRF-Token": token,
                                              "Origin": "http://outside.example"}).status_code, 403)

    def test_read_burst_does_not_block_booking_proposal(self):
        security._requests.clear()
        try:
            client = app.test_client()
            token = client.get("/api/session").json["csrf_token"]
            for _ in range(60):
                self.assertEqual(client.get("/api/session").status_code, 200)
            response = client.post("/api/booking-proposals",
                                   json={"project_code": "XM-2026-001", "asset_code": "SH-LED-P3-02"},
                                   headers={"X-CSRF-Token": token})
            self.assertEqual(response.status_code, 200)
        finally:
            security._requests.clear()

    def test_booking_role_cannot_change_projects(self):
        with booking_connection() as conn:
            with self.assertRaises(Exception):
                conn.execute("UPDATE projects SET status = 'confirmed' WHERE false")

    def test_booking_idempotency_and_parallel_conflict(self):
        asset = "SH-LED-P3-02"
        first = booking.proposal("XM-2026-001", asset)
        second = booking.proposal("XM-2026-002", asset)
        keys = [first["request_key"], second["request_key"]]
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(booking.confirm, item["token"]) for item in (first, second)]
                outcomes = []
                for future in futures:
                    try:
                        outcomes.append(future.result())
                    except booking.BookingError as exc:
                        self.assertEqual(exc.status, 409)
            self.assertEqual(len(outcomes), 1)
            winner = first if outcomes[0]["project_code"] == first["project_code"] else second
            retry = booking.confirm(winner["token"])
            self.assertTrue(retry["idempotent"])
            self.assertEqual(retry["reservation_id"], outcomes[0]["reservation_id"])
        finally:
            with admin_connection("xingmu_equipment") as conn:
                conn.execute("DELETE FROM reservations WHERE request_key = ANY(%s::uuid[])", (keys,))
                conn.execute("DELETE FROM booking_audit WHERE request_key = ANY(%s::uuid[])", (keys,))

    def test_parallel_retry_creates_one_reservation(self):
        item = booking.proposal("XM-2026-001", "SH-LED-P3-03")
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(booking.confirm, item["token"]) for _ in range(2)]
                results = [future.result() for future in futures]
            self.assertEqual(results[0]["reservation_id"], results[1]["reservation_id"])
            self.assertEqual(sorted(result["idempotent"] for result in results), [False, True])
        finally:
            with admin_connection("xingmu_equipment") as conn:
                conn.execute("DELETE FROM reservations WHERE request_key = %s", (item["request_key"],))
                conn.execute("DELETE FROM booking_audit WHERE request_key = %s", (item["request_key"],))


if __name__ == "__main__":
    unittest.main()
