"""
Group Message Order Tester - Total Order Multicast Simulator
Backend: Python Flask
Description: Centralized Sequencer based Total Order Multicast simulation.
"""

from flask import Flask, render_template, request, jsonify
from datetime import datetime
import threading

app = Flask(__name__)

# Thread-safe lock taaki concurrent requests ke waqt state corrupt na ho
# (Flask server multi-threaded request handle kar sakta hai, isliye lock zaroori hai)
state_lock = threading.Lock()

# Global In-Memory Simulation State
# Isme Sequencer, teeno processes (P1, P2, P3), aur event logs store hote hain
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
    """
    Hinglish: Yeh function timeline ke liye ek naya formatted event log add karta hai.
    """
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
    """
    Hinglish: Dashboard homepage render karta hai.
    """
    return render_template("index.html")


@app.route("/api/send", methods=["POST"])
def send_message():
    """
    Hinglish: User jab message submit karta hai, tab yeh endpoint:
    1. Input validate karta hai (sender valid ho, text empty na ho).
    2. Central Sequencer monotonically increasing Sequence Number assign karta hai.
    3. Sequencer message list aur log update karta hai.
    """
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
        # Sequencer monotonically increasing sequence number deta hai
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

        # Log creation and sequencing
        add_log(
            event_type="SUBMITTED",
            process_id="SYSTEM",
            message_id=msg_id,
            seq=seq_num,
            description=f"User ne '{sender}' ke through message submit kiya: \"{content}\""
        )
        add_log(
            event_type="SEQUENCED",
            process_id="SEQUENCER",
            message_id=msg_id,
            seq=seq_num,
            description=f"Central Sequencer ne message '{msg_id}' ko Sequence Number #{seq_num} assign kiya."
        )

        return jsonify({
            "success": True,
            "message": new_message,
            "sequencer": simulation_state["sequencer"]
        }), 201


@app.route("/api/process/arrive", methods=["POST"])
def process_arrival():
    """
    Hinglish: Jab message kisi process (P1/P2/P3) par arrive hota hai:
    - Agar sequence number process ke expected sequence number ke barabar hai, toh message turant DELIVER ho jata hai.
    - Expected sequence number ko 1 se badha diya jata hai.
    - Phir pending queue check hoti hai ki kya agla sequence number pehle se pending tha (Cascading Delivery).
    - Agar sequence number bada hai, toh message ko PENDING queue mein hold kiya jata hai.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "Invalid JSON payload"}), 400

    process_id = data.get("process_id")
    message_id = data.get("message_id")
    delay_ms = data.get("delay_ms", 0)

    if process_id not in simulation_state["processes"]:
        return jsonify({"success": False, "error": f"Invalid process_id. Must be P1, P2, or P3"}), 400

    with state_lock:
        # Message ko sequencer ki list se find karte hain
        target_msg = None
        for msg in simulation_state["sequencer"]["messages"]:
            if msg["id"] == message_id:
                target_msg = msg
                break

        if not target_msg:
            return jsonify({"success": False, "error": f"Message {message_id} not found in Sequencer"}), 404

        proc = simulation_state["processes"][process_id]

        # Duplicate check - agar yeh message pehle hi receive ho chuka hai
        already_received = any(m["id"] == message_id for m in proc["received"])
        if already_received:
            return jsonify({"success": False, "error": f"Message {message_id} already received by {process_id}"}), 409

        # 1. Received buffer mein add karo
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
            description=f"Message '{message_id}' (Seq #{seq}) process {process_id} par arrive hua (Delay: {delay_ms}ms)."
        )

        delivered_now = []

        # 2. Check: Kya sequence number process ke expected_seq ke barabar hai?
        if seq == proc["expected_seq"]:
            # Delivery allowed!
            proc["delivered"].append(dict(target_msg))
            proc["expected_seq"] += 1
            delivered_now.append(target_msg)

            add_log(
                event_type="DELIVERED",
                process_id=process_id,
                message_id=message_id,
                seq=seq,
                description=f"Process {process_id} ne message '{message_id}' (Seq #{seq}) deliver kiya. Next expected seq: #{proc['expected_seq']}."
            )

            # 3. Cascading check: Kya pending buffer mein ab next expected message maujood hai?
            # Yeh loop tab tak chalega jab tak consecutive pending messages deliver na ho jayein
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
                        description=f"Cascading Delivery: Pending queue se message '{found_next['id']}' (Seq #{found_next['seq']}) deliver hua process {process_id} par. Next expected seq: #{proc['expected_seq']}."
                    )
                else:
                    break

        elif seq > proc["expected_seq"]:
            # Out-of-order arrival: Message ko pending buffer mein hold karo
            proc["pending"].append(dict(target_msg))
            # Pending list ko sequence order mein sort karke rakhte hain display clarity ke liye
            proc["pending"].sort(key=lambda m: m["seq"])

            add_log(
                event_type="PENDING",
                process_id=process_id,
                message_id=message_id,
                seq=seq,
                description=f"Out-of-Order arrival! Message '{message_id}' (Seq #{seq}) ko buffer mein hold kiya gaya kyunki process {process_id} ko Sequence #{proc['expected_seq']} ka intezar hai."
            )
        else:
            # seq < expected_seq (purana message jo pehle deliver ho chuka ho)
            pass

        return jsonify({
            "success": True,
            "process": proc,
            "delivered_now": delivered_now
        }), 200


@app.route("/api/state", methods=["GET"])
def get_state():
    """
    Hinglish: Current simulation ka complete state return karta hai.
    """
    with state_lock:
        return jsonify({
            "success": True,
            "state": simulation_state
        }), 200


@app.route("/api/reset", methods=["POST"])
def reset_simulation():
    """
    Hinglish: Sabhi counters, buffers, logs aur delivery histories ko reset karta hai.
    """
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
            description="Simulation state reset ho gaya. Sabhi buffers aur sequence counters initialize kar diye gaye."
        )

        return jsonify({
            "success": True,
            "message": "Simulation reset successfully",
            "state": simulation_state
        }), 200


@app.route("/api/verify", methods=["GET"])
def verify_total_order():
    """
    Hinglish: Total Order property verify karta hai:
    - Teeno processes (P1, P2, P3) ki delivered sequence ko compare karta hai.
    - Agar teeno ke delivered message IDs exact same sequence mein hain, toh PASS.
    - Agar kisi process ka delivery order alag hai, toh FAIL.
    - Agar delivery abhi chal rahi hai aur kuch messages pending hain, toh IN_PROGRESS.
    """
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
            explanation = "Abhi tak koi message send nahi kiya gaya hai. Simulation ready state mein hai."
        elif not is_prefix_consistent:
            status = "FAIL"
            is_pass = False
            explanation = (
                f"FAIL: Total Order Violated! Processes ki delivery sequences aapas mein contradict kar rahi hain: "
                f"P1={p1_del}, P2={p2_del}, P3={p3_del}."
            )
        elif p1_del == p2_del == p3_del and len(p1_del) == total_messages and total_pending == 0:
            status = "PASS"
            is_pass = True
            order_display = " -> ".join(p1_del) if p1_del else "None"
            explanation = (
                f"PASS: Total Order Satisfied! Sabhi 3 processes (P1, P2, P3) ne sabhi {total_messages} messages "
                f"ko exact same global order [{order_display}] mein deliver kiya hai. "
                "Bhale hi network delay ke chalte packets alag-alag arrival time par aaye, "
                "Central Sequencer aur Pending Queue ne order preserve rakha."
            )
        else:
            status = "IN_PROGRESS"
            is_pass = True
            delivered_summary = f"P1={len(p1_del)}, P2={len(p2_del)}, P3={len(p3_del)}"
            explanation = (
                f"IN PROGRESS: Multicast transit chal raha hai ({delivered_summary} delivered / {total_messages} total). "
                f"Ab tak ki deliveries Total Order ke saath consistent hain. "
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
    # Local development server run karne ke liye
    # Production deployment ke waqt Gunicorn ya Waitress use hoga
    app.run(host="127.0.0.1", port=5000, debug=False)
