"""
Automated Test Suite for Group Message Order Tester
Tests all 8 required scenarios:
1. Basic in-order delivery
2. Out-of-order arrival & pending buffer hold & cascading release
3. Different process delays & arrival order divergence vs delivery order convergence
4. Empty message validation
5. Reset functionality (counters, buffers, logs, histories)
6. Total-order verification (PASS on match, FAIL on mismatch detection)
7. Dashboard route & template rendering (Desktop/Mobile responsiveness tags)
8. Backend error handling (invalid sender, oversized message, invalid process, duplicate arrivals)
"""

import unittest
import json
from app import app, simulation_state


class TestTotalOrderMulticast(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        # Reset simulation before each test
        self.client.post("/api/reset")

    def test_scenario_4_empty_and_invalid_inputs(self):
        """Test 4: Verify empty messages and invalid fields are rejected"""
        # Empty content
        resp = self.client.post("/api/send", json={"sender": "Alice", "content": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("empty", resp.get_json()["error"].lower())

        # Whitespace only content
        resp = self.client.post("/api/send", json={"sender": "Alice", "content": "   "})
        self.assertEqual(resp.status_code, 400)

        # Invalid sender
        resp = self.client.post("/api/send", json={"sender": "Eve", "content": "Malicious"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("invalid sender", resp.get_json()["error"].lower())

        # Exceeds max length (200 chars)
        long_text = "A" * 205
        resp = self.client.post("/api/send", json={"sender": "Bob", "content": long_text})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("too long", resp.get_json()["error"].lower())

    def test_scenario_1_basic_delivery(self):
        """Test 1: Send three messages and verify P1, P2, P3 deliver the same sequence"""
        # Submit 3 messages
        r1 = self.client.post("/api/send", json={"sender": "Alice", "content": "Msg 1"}).get_json()
        r2 = self.client.post("/api/send", json={"sender": "Bob", "content": "Msg 2"}).get_json()
        r3 = self.client.post("/api/send", json={"sender": "Charlie", "content": "Msg 3"}).get_json()

        m1_id = r1["message"]["id"]
        m2_id = r2["message"]["id"]
        m3_id = r3["message"]["id"]

        # Deliver in order to P1, P2, P3
        for proc in ["P1", "P2", "P3"]:
            for m_id in [m1_id, m2_id, m3_id]:
                arr_resp = self.client.post("/api/process/arrive", json={
                    "process_id": proc,
                    "message_id": m_id,
                    "delay_ms": 100
                })
                self.assertEqual(arr_resp.status_code, 200)

        # Verify state
        state = self.client.get("/api/state").get_json()["state"]
        for proc in ["P1", "P2", "P3"]:
            delivered_ids = [m["id"] for m in state["processes"][proc]["delivered"]]
            self.assertEqual(delivered_ids, [m1_id, m2_id, m3_id])
            self.assertEqual(len(state["processes"][proc]["pending"]), 0)
            self.assertEqual(state["processes"][proc]["expected_seq"], 4)

        # Verification endpoint should report PASS
        verif = self.client.get("/api/verify").get_json()
        self.assertEqual(verif["status"], "PASS")
        self.assertTrue(verif["is_total_order"])

    def test_scenario_2_out_of_order_arrival_and_cascading_release(self):
        """
        Test 2: Make sequence 2 arrive before sequence 1 at a process.
        Verify message 2 remains pending until message 1 arrives, then both deliver!
        """
        r1 = self.client.post("/api/send", json={"sender": "Alice", "content": "First"}).get_json()
        r2 = self.client.post("/api/send", json={"sender": "Bob", "content": "Second"}).get_json()
        m1_id = r1["message"]["id"]
        m2_id = r2["message"]["id"]

        # Sequence 2 arrives FIRST at P2!
        arr2 = self.client.post("/api/process/arrive", json={
            "process_id": "P2",
            "message_id": m2_id,
            "delay_ms": 500
        }).get_json()
        self.assertTrue(arr2["success"])

        # Check P2 state: MSG-2 must be in pending buffer, 0 delivered, expected_seq still 1!
        p2_state = self.client.get("/api/state").get_json()["state"]["processes"]["P2"]
        self.assertEqual(len(p2_state["delivered"]), 0, "MSG-2 must NOT be delivered before MSG-1")
        self.assertEqual(len(p2_state["pending"]), 1, "MSG-2 must be in pending buffer")
        self.assertEqual(p2_state["pending"][0]["id"], m2_id)
        self.assertEqual(p2_state["expected_seq"], 1, "Expected seq must still be 1")

        # Now MSG-1 arrives at P2!
        arr1 = self.client.post("/api/process/arrive", json={
            "process_id": "P2",
            "message_id": m1_id,
            "delay_ms": 1200
        }).get_json()
        self.assertTrue(arr1["success"])

        # Check P2 state: MSG-1 delivered, and MSG-2 automatically cascading delivered!
        p2_state_after = self.client.get("/api/state").get_json()["state"]["processes"]["P2"]
        self.assertEqual(len(p2_state_after["pending"]), 0, "Pending buffer must now be empty")
        self.assertEqual(len(p2_state_after["delivered"]), 2, "Both messages must be delivered")
        self.assertEqual([m["id"] for m in p2_state_after["delivered"]], [m1_id, m2_id])
        self.assertEqual(p2_state_after["expected_seq"], 3)

    def test_scenario_3_different_process_delays_and_arrival_orders(self):
        """
        Test 3: Different process delays where physical arrival orders completely differ:
        P1 receives: MSG 1 -> MSG 2 -> MSG 3
        P2 receives: MSG 2 -> MSG 3 -> MSG 1 (MSG 2, 3 held pending until MSG 1 arrives)
        P3 receives: MSG 3 -> MSG 1 -> MSG 2
        Verify completed delivery histories match exactly!
        """
        r1 = self.client.post("/api/send", json={"sender": "Alice", "content": "Alpha"}).get_json()
        r2 = self.client.post("/api/send", json={"sender": "Bob", "content": "Beta"}).get_json()
        r3 = self.client.post("/api/send", json={"sender": "Charlie", "content": "Gamma"}).get_json()
        m1, m2, m3 = r1["message"]["id"], r2["message"]["id"], r3["message"]["id"]

        # P1 arrival order: 1, 2, 3
        for m in [m1, m2, m3]:
            self.client.post("/api/process/arrive", json={"process_id": "P1", "message_id": m, "delay_ms": 100})

        # P2 arrival order: 2, 3, 1
        for m in [m2, m3, m1]:
            self.client.post("/api/process/arrive", json={"process_id": "P2", "message_id": m, "delay_ms": 200})

        # P3 arrival order: 3, 1, 2
        for m in [m3, m1, m2]:
            self.client.post("/api/process/arrive", json={"process_id": "P3", "message_id": m, "delay_ms": 300})

        state = self.client.get("/api/state").get_json()["state"]

        # Arrival histories are DIFFERENT
        p1_recv = [m["id"] for m in state["processes"]["P1"]["received"]]
        p2_recv = [m["id"] for m in state["processes"]["P2"]["received"]]
        p3_recv = [m["id"] for m in state["processes"]["P3"]["received"]]
        self.assertEqual(p1_recv, [m1, m2, m3])
        self.assertEqual(p2_recv, [m2, m3, m1])
        self.assertEqual(p3_recv, [m3, m1, m2])
        self.assertNotEqual(p1_recv, p2_recv)

        # BUT Delivery histories are IDENTICAL (Total Order Satisfied!)
        p1_del = [m["id"] for m in state["processes"]["P1"]["delivered"]]
        p2_del = [m["id"] for m in state["processes"]["P2"]["delivered"]]
        p3_del = [m["id"] for m in state["processes"]["P3"]["delivered"]]
        self.assertEqual(p1_del, [m1, m2, m3])
        self.assertEqual(p2_del, [m1, m2, m3])
        self.assertEqual(p3_del, [m1, m2, m3])

        verif = self.client.get("/api/verify").get_json()
        self.assertEqual(verif["status"], "PASS")

    def test_scenario_5_reset(self):
        """Test 5: Verify reset clears all counters, buffers, logs, and delivery histories"""
        self.client.post("/api/send", json={"sender": "Alice", "content": "Temporary"})
        self.client.post("/api/process/arrive", json={"process_id": "P1", "message_id": "MSG-001"})

        # Call reset
        reset_resp = self.client.post("/api/reset")
        self.assertEqual(reset_resp.status_code, 200)

        state = self.client.get("/api/state").get_json()["state"]
        self.assertEqual(state["sequencer"]["next_seq"], 1)
        self.assertEqual(len(state["sequencer"]["messages"]), 0)

        for proc in ["P1", "P2", "P3"]:
            self.assertEqual(state["processes"][proc]["expected_seq"], 1)
            self.assertEqual(len(state["processes"][proc]["received"]), 0)
            self.assertEqual(len(state["processes"][proc]["pending"]), 0)
            self.assertEqual(len(state["processes"][proc]["delivered"]), 0)

    def test_scenario_6_total_order_verification_failure_detection(self):
        """
        Test 6: Verify total order checker detects differing delivery histories
        instead of blindly returning PASS.
        """
        # Artificially alter delivery history of P2 to simulate a corrupted/failed node
        r1 = self.client.post("/api/send", json={"sender": "Alice", "content": "A"}).get_json()
        r2 = self.client.post("/api/send", json={"sender": "Bob", "content": "B"}).get_json()

        # Artificially alter delivery history of P2 to simulate a corrupted/failed node
        simulation_state["processes"]["P1"]["delivered"] = [
            {"id": "MSG-001", "seq": 1}, {"id": "MSG-002", "seq": 2}
        ]
        simulation_state["processes"]["P2"]["delivered"] = [
            {"id": "MSG-002", "seq": 2}, {"id": "MSG-001", "seq": 1} # Inverted order!
        ]
        simulation_state["processes"]["P3"]["delivered"] = [
            {"id": "MSG-001", "seq": 1}, {"id": "MSG-002", "seq": 2}
        ]

        verif = self.client.get("/api/verify").get_json()
        self.assertEqual(verif["status"], "FAIL", "Checker MUST fail if delivery order differs")
        self.assertFalse(verif["is_total_order"])
        self.assertIn("Violated", verif["explanation"])

    def test_scenario_7_route_and_html_rendering(self):
        """Test 7: Verify index route serves responsive HTML dashboard"""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Group Message Order Tester", html)
        self.assertIn("viewport", html)
        self.assertIn("Centralized Sequencer", html)
        self.assertIn("Total Order Multicast Verification", html)

    def test_scenario_8_backend_error_handling(self):
        """Test 8: Check invalid process ID, non-existent messages, duplicate arrivals"""
        # Invalid process ID
        resp = self.client.post("/api/process/arrive", json={
            "process_id": "P99",
            "message_id": "MSG-001"
        })
        self.assertEqual(resp.status_code, 400)

        # Message not found
        resp = self.client.post("/api/process/arrive", json={
            "process_id": "P1",
            "message_id": "MSG-999"
        })
        self.assertEqual(resp.status_code, 404)

        # Duplicate arrival
        self.client.post("/api/send", json={"sender": "Alice", "content": "Dup Test"})
        arr1 = self.client.post("/api/process/arrive", json={"process_id": "P1", "message_id": "MSG-001"})
        self.assertEqual(arr1.status_code, 200)

        # Arrive again should return 409 Conflict
        arr2 = self.client.post("/api/process/arrive", json={"process_id": "P1", "message_id": "MSG-001"})
        self.assertEqual(arr2.status_code, 409)


if __name__ == "__main__":
    unittest.main(verbosity=2)
