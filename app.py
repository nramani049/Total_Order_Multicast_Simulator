"""
Group Message Order Tester - Total Order Multicast Simulator
Backend: Python Flask
Centralized Sequencer based Total Order Multicast simulation.
"""

from flask import Flask, render_template, request, jsonify
from datetime import datetime
import threading

app = Flask(__name__)

# Thread-safe lock to prevent race conditions during concurrent requests
state_lock = threading.Lock()

# Global in-memory simulation state
simulation_state = {
    "sequencer": {
        "next_seq": 1,
        "messages": []
    },
    "processes": {
        "P1": {
            "id": "P1",
            "name": "Alice",
            "expected_seq": 1,
            "received": [],
            "pending": [],
            "delivered": []
        },
        "P2": {
            "id": "P2",
            "name": "Bob",
            "expected_seq": 1,
            "received": [],
            "pending": [],
            "delivered": []
        },
        "P3": {
            "id": "P3",
            "name": "Charlie",
            "expected_seq": 1,
            "received": [],
            "pending": [],
            "delivered": []
        }
    },
    "logs": [],
    "log_counter": 0
}


def add_log(event_type, process_id, message_id, seq, description):
    """Add a structured event entry to the timeline log."""
    simulation_state["log_counter"] += 1
    log_entry = {
        "id": simulation_state["log_counter"],
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "type": event_type,       # SUBMITTED, SEQUENCED, ARRIVED, PENDING, DELIVERED, RESET
        "process_id": process_id, # 'SEQUENCER', 'P1', 'P2', 'P3', 'SYSTEM'
        "message_id": message_id,
        "seq": seq,
        "description": description
    }
    simulation_state["logs"].append(log_entry)
    return log_entry


@app.route("/")
def index():
    """Render the simulation dashboard."""
    return render_template("index.html")


@app.route("/api/send", methods=["POST"])
def send_message():
    """Validate message input and assign sequence number via Central Sequencer."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "Invalid JSON payload"}), 400

    sender = data.get("sender", "").strip()
    content = data.get("content", "").strip()

    # Input validation
    valid_senders = ["Alice", "Bob", "Charlie"]
    if sender not in valid_senders:
        return jsonify({"success": False, "error": f"Invalid sender. Must be one of {valid_senders}"}), 400

    if not content:
        return jsonify({"success": False, "error": "Message content cannot be empty"}), 400

    if len(content) > 200:
        return jsonify({"success": False, "error": "Message is too long (maximum 200 characters allowed)"}), 400

    with state_lock:
        seq_num = simulation_state["sequencer"]["next_seq"]
        simulation_state["sequencer"]["next_seq"] += 1

        msg_id = f"MSG-{seq_num:03d}"
        now_str = datetime.now().strftime("%H:%M:%S")

        new_message = {
            "id": msg_id,
            "sender": sender,
            "content": content,
            "seq": seq_num,
            "created_at": now_str
        }

        simulation_state["sequencer"]["messages"].append(new_message)

        add_log(
            event_type="SUBMITTED",
            process_id="SYSTEM",
            message_id=msg_id,
            seq=seq_num,
            description=f"Message submitted by '{sender}': \"{content}\""
        )
        add_log(
            event_type="SEQUENCED",
            process_id="SEQUENCER",
            message_id=msg_id,
            seq=seq_num,
            description=f"Central Sequencer assigned Sequence #{seq_num} to message '{msg_id}'."
        )

        return jsonify({
            "success": True,
            "message": new_message,
            "sequencer": simulation_state["sequencer"]
        }), 201


@app.route("/api/process/arrive", methods=["POST"])
def process_arrival():
    """Handle message arrival at a process node, manage buffers, and trigger cascading delivery."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "Invalid JSON payload"}), 400

    process_id = data.get("process_id")
    message_id = data.get("message_id")
    delay_ms = data.get("delay_ms", 0)

    if process_id not in simulation_state["processes"]:
        return jsonify({"success": False, "error": f"Invalid process_id. Must be P1, P2, or P3"}), 400

    with state_lock:
        target_msg = None
        for msg in simulation_state["sequencer"]["messages"]:
            if msg["id"] == message_id:
                target_msg = msg
                break

        if not target_msg:
            return jsonify({"success": False, "error": f"Message {message_id} not found in Sequencer"}), 404

        proc = simulation_state["processes"][process_id]

        already_received = any(m["id"] == message_id for m in proc["received"])
        if already_received:
            return jsonify({"success": False, "error": f"Message {message_id} already received by {process_id}"}), 409

        received_record = dict(target_msg)
        received_record["arrival_delay_ms"] = delay_ms
        received_record["arrived_at"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        proc["received"].append(received_record)

        seq = target_msg["seq"]
        add_log(
            event_type="ARRIVED",
            process_id=process_id,
            message_id=message_id,
            seq=seq,
            description=f"Message '{message_id}' (Seq #{seq}) arrived at process {process_id} (Delay: {delay_ms}ms)."
        )

        delivered_now = []

        if seq == proc["expected_seq"]:
            proc["delivered"].append(dict(target_msg))
            proc["expected_seq"] += 1
            delivered_now.append(target_msg)

            add_log(
                event_type="DELIVERED",
                process_id=process_id,
                message_id=message_id,
                seq=seq,
                description=f"Process {process_id} delivered message '{message_id}' (Seq #{seq}). Next expected sequence: #{proc['expected_seq']}."
            )

            # Cascading delivery: check if subsequent expected messages are waiting in pending buffer
            while True:
                found_next = None
                for pend_msg in proc["pending"]:
                    if pend_msg["seq"] == proc["expected_seq"]:
                        found_next = pend_msg
                        break

                if found_next:
                    proc["pending"].remove(found_next)
                    proc["delivered"].append(dict(found_next))
                    proc["expected_seq"] += 1
                    delivered_now.append(found_next)

                    add_log(
                        event_type="DELIVERED",
                        process_id=process_id,
                        message_id=found_next["id"],
                        seq=found_next["seq"],
                        description=f"Cascading Delivery: Pending message '{found_next['id']}' (Seq #{found_next['seq']}) delivered at {process_id}. Next expected sequence: #{proc['expected_seq']}."
                    )
                else:
                    break

        elif seq > proc["expected_seq"]:
            proc["pending"].append(dict(target_msg))
            proc["pending"].sort(key=lambda m: m["seq"])

            add_log(
                event_type="PENDING",
                process_id=process_id,
                message_id=message_id,
                seq=seq,
                description=f"Out-of-Order arrival: Message '{message_id}' (Seq #{seq}) buffered at {process_id} awaiting Sequence #{proc['expected_seq']}."
            )
        else:
            # Message sequence precedes expected sequence; ignore duplicate/stale arrival
            pass

        return jsonify({
            "success": True,
            "process": proc,
            "delivered_now": delivered_now
        }), 200


@app.route("/api/state", methods=["GET"])
def get_state():
    """Return current simulation state."""
    with state_lock:
        return jsonify({
            "success": True,
            "state": simulation_state
        }), 200


@app.route("/api/reset", methods=["POST"])
def reset_simulation():
    """Reset all buffers, counters, and logs."""
    with state_lock:
        simulation_state["sequencer"]["next_seq"] = 1
        simulation_state["sequencer"]["messages"] = []

        for p_id in simulation_state["processes"]:
            simulation_state["processes"][p_id]["expected_seq"] = 1
            simulation_state["processes"][p_id]["received"] = []
            simulation_state["processes"][p_id]["pending"] = []
            simulation_state["processes"][p_id]["delivered"] = []

        simulation_state["logs"] = []
        simulation_state["log_counter"] = 0

        add_log(
            event_type="RESET",
            process_id="SYSTEM",
            message_id="ALL",
            seq=0,
            description="Simulation state reset. All buffers and sequence counters reinitialized."
        )

        return jsonify({
            "success": True,
            "message": "Simulation reset successfully",
            "state": simulation_state
        }), 200


@app.route("/api/verify", methods=["GET"])
def verify_total_order():
    """Verify total order consistency across all process delivery histories."""
    with state_lock:
        p1_del = [m["id"] for m in simulation_state["processes"]["P1"]["delivered"]]
        p2_del = [m["id"] for m in simulation_state["processes"]["P2"]["delivered"]]
        p3_del = [m["id"] for m in simulation_state["processes"]["P3"]["delivered"]]

        p1_seqs = [m["seq"] for m in simulation_state["processes"]["P1"]["delivered"]]
        p2_seqs = [m["seq"] for m in simulation_state["processes"]["P2"]["delivered"]]
        p3_seqs = [m["seq"] for m in simulation_state["processes"]["P3"]["delivered"]]

        total_messages = len(simulation_state["sequencer"]["messages"])
        pending_counts = {
            p_id: len(simulation_state["processes"][p_id]["pending"])
            for p_id in simulation_state["processes"]
        }
        total_pending = sum(pending_counts.values())
        total_arrivals = sum(len(simulation_state["processes"][p]["received"]) for p in simulation_state["processes"])
        expected_total_arrivals = total_messages * 3

        # Check if histories are prefix-consistent with each other
        histories = [p1_del, p2_del, p3_del]
        longest_history = max(histories, key=len) if histories else []
        is_prefix_consistent = all(
            longest_history[:len(h)] == h for h in histories
        )

        if total_messages == 0:
            status = "EMPTY"
            is_pass = True
            explanation = "No messages sent yet. Simulation is ready."
        elif not is_prefix_consistent:
            status = "FAIL"
            is_pass = False
            explanation = (
                f"FAIL: Total Order Violated! Delivery sequences contradict across processes: "
                f"P1={p1_del}, P2={p2_del}, P3={p3_del}."
            )
        elif p1_del == p2_del == p3_del and len(p1_del) == total_messages and total_pending == 0:
            status = "PASS"
            is_pass = True
            order_display = " -> ".join(p1_del) if p1_del else "None"
            explanation = (
                f"PASS: Total Order Satisfied! All 3 processes (P1, P2, P3) delivered all {total_messages} messages "
                f"in identical global order [{order_display}]."
            )
        else:
            status = "IN_PROGRESS"
            is_pass = True
            delivered_summary = f"P1={len(p1_del)}, P2={len(p2_del)}, P3={len(p3_del)}"
            explanation = (
                f"IN PROGRESS: Multicast transit in progress ({delivered_summary} delivered / {total_messages} total). "
                f"Current deliveries are consistent with Total Order. "
                f"Pending queue: P1={pending_counts['P1']}, P2={pending_counts['P2']}, P3={pending_counts['P3']}."
            )

        verification_result = {
            "status": status,
            "is_total_order": is_pass,
            "total_messages": total_messages,
            "histories": {
                "P1": p1_del,
                "P2": p2_del,
                "P3": p3_del
            },
            "sequence_numbers": {
                "P1": p1_seqs,
                "P2": p2_seqs,
                "P3": p3_seqs
            },
            "pending_counts": pending_counts,
            "explanation": explanation
        }

        return jsonify(verification_result), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)

