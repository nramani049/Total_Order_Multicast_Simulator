/**
 * Group Message Order Tester - Total Order Multicast Simulator
 * Frontend Logic (Vanilla JavaScript)
 * Hinglish: Yeh script message submit karne, transit timers simulate karne,
 * buffers update karne aur total order verify karne ka kaam karti hai.
 */

// Active scheduled transit timers (Reset ke waqt cancel karne ke liye)
let activeTransitTimers = [];

// Simulation pause state
let isSimulationPaused = false;
let pausedQueue = [];

// Random delay flag
let isRandomDelayEnabled = false;

// DOM load hote hi simulation ka current state fetch karte hain
document.addEventListener("DOMContentLoaded", () => {
    fetchSimulationState();
});

/**
 * Hinglish: Backend se current simulation state lekar pura UI refresh karta hai.
 */
async function fetchSimulationState() {
    try {
        const response = await fetch("/api/state");
        const data = await response.json();
        if (data.success) {
            renderDashboard(data.state);
            checkTotalOrderVerification();
        }
    } catch (err) {
        console.error("State fetch error:", err);
    }
}

/**
 * Hinglish: User jab "Send Message" click karta hai:
 * 1. Sender aur content ko validate karta hai.
 * 2. Backend /api/send par bhejta hai (Central Sequencer sequence number assign karta hai).
 * 3. Sequenced message ko teeno processes (P1, P2, P3) ke liye multicast transit par schedule karta hai.
 */
async function handleSendMessage(event) {
    event.preventDefault();

    const senderSelect = document.getElementById("sender-select");
    const messageInput = document.getElementById("message-input");
    const feedbackBanner = document.getElementById("composer-feedback");

    const sender = senderSelect.value;
    const content = messageInput.value.trim();

    if (!content) {
        showFeedback("Please enter message content.", "error");
        return;
    }

    // Disable button momentarily
    const sendBtn = document.getElementById("btn-send-message");
    sendBtn.disabled = true;

    try {
        const response = await fetch("/api/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sender, content })
        });

        const data = await response.json();

        if (response.ok && data.success) {
            const message = data.message;
            showFeedback(`Message '${message.id}' (Seq #${message.seq}) submitted to Central Sequencer!`, "success");
            messageInput.value = "";

            // UI update Sequencer section
            updateSystemStatus("Simulating Multicast...", "badge-simulating");
            fetchSimulationState();

            // Sequenced message ko teeno processes (P1, P2, P3) par multicast transit simulate karo
            multicastMessageToProcesses(message);
        } else {
            showFeedback(data.error || "Failed to submit message", "error");
        }
    } catch (err) {
        showFeedback("Network error connecting to Flask backend.", "error");
        console.error("Send error:", err);
    } finally {
        sendBtn.disabled = false;
    }
}

/**
 * Hinglish: Message ko P1, P2, aur P3 tak alag-alag delay ke saath schedule karta hai.
 * Yeh function simulate karta hai ki network mein packets travel kar rahe hain.
 */
function multicastMessageToProcesses(message, customDelays = null) {
    const processes = ["P1", "P2", "P3"];

    processes.forEach((procId) => {
        let delayMs = 1000;

        if (customDelays && customDelays[procId] !== undefined) {
            delayMs = customDelays[procId];
        } else if (isRandomDelayEnabled) {
            // Random delay: 400ms se 3500ms ke beech
            delayMs = Math.floor(Math.random() * 3100) + 400;
        } else {
            // Manual delay sliders se value padho
            const sliderId = `delay-${procId.toLowerCase()}`;
            const slider = document.getElementById(sliderId);
            delayMs = slider ? parseInt(slider.value, 10) : 1000;
        }

        // Timer create karke process arrival call karo
        const timerId = setTimeout(() => {
            if (isSimulationPaused) {
                // Agar paused hai toh pending queue mein rakh lo
                pausedQueue.push({ procId, messageId: message.id, delayMs });
            } else {
                dispatchArrival(procId, message.id, delayMs);
            }
        }, delayMs);

        activeTransitTimers.push(timerId);
    });
}

/**
 * Hinglish: Jab transit timer expire hota hai, toh yeh function
 * backend /api/process/arrive ko call karke process buffer update karwata hai.
 */
async function dispatchArrival(processId, messageId, delayMs) {
    try {
        const response = await fetch("/api/process/arrive", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                process_id: processId,
                message_id: messageId,
                delay_ms: delayMs
            })
        });

        const data = await response.json();
        if (data.success) {
            // State update karo aur verification check karo
            await fetchSimulationState();
        }
    } catch (err) {
        console.error(`Arrival dispatch error for ${processId}:`, err);
    }
}

/**
 * Hinglish: Pura dashboard render karta hai (Sequencer, P1, P2, P3, Timeline).
 */
function renderDashboard(state) {
    if (!state) return;

    // 1. Header & Sequencer status
    const nextSeq = state.sequencer.next_seq;
    document.getElementById("header-next-seq").textContent = nextSeq;
    document.getElementById("sequencer-total-count").textContent = state.sequencer.messages.length;

    // 2. Sequencer Table
    renderSequencerTable(state.sequencer.messages);

    // 3. Process Cards (P1, P2, P3)
    renderProcessNode("P1", state.processes.P1);
    renderProcessNode("P2", state.processes.P2);
    renderProcessNode("P3", state.processes.P3);

    // 4. Timeline
    renderTimeline(state.logs);
}

/**
 * Hinglish: Central Sequencer ki table update karta hai.
 */
function renderSequencerTable(messages) {
    const tbody = document.getElementById("sequencer-messages-body");
    if (!messages || messages.length === 0) {
        tbody.innerHTML = `
            <tr class="empty-row">
                <td colspan="6">No messages sequenced yet. Send a message above to start!</td>
            </tr>`;
        return;
    }

    let rowsHtml = "";
    messages.forEach((msg) => {
        rowsHtml += `
            <tr>
                <td><span class="seq-tag">#${msg.seq}</span></td>
                <td><strong>${escapeHtml(msg.id)}</strong></td>
                <td>${escapeHtml(msg.sender)}</td>
                <td>${escapeHtml(msg.content)}</td>
                <td><small class="text-muted">${msg.created_at}</small></td>
                <td><span class="node-badge" style="background:#e0f2fe; color:#0369a1;">Multicast Dispatched</span></td>
            </tr>
        `;
    });
    tbody.innerHTML = rowsHtml;
}

/**
 * Hinglish: Ek process card (P1/P2/P3) ke buffers ko render karta hai:
 * - Received list (Physical arrivals)
 * - Pending list (Held because Seq > Expected)
 * - Delivered list (Total Order Delivery)
 */
function renderProcessNode(procId, procData) {
    if (!procData) return;

    const lowerId = procId.toLowerCase();

    // Next Expected Seq Number
    document.getElementById(`${lowerId}-expected-seq`).textContent = procData.expected_seq;

    // Status pill
    const statusPill = document.getElementById(`${lowerId}-status-pill`);
    if (procData.pending.length > 0) {
        statusPill.textContent = "Holding Pending";
        statusPill.style.background = "#ffedd5";
        statusPill.style.color = "#9a3412";
    } else if (procData.delivered.length > 0) {
        statusPill.textContent = "Synchronized";
        statusPill.style.background = "#dcfce7";
        statusPill.style.color = "#166534";
    } else {
        statusPill.textContent = "Active / Idle";
        statusPill.style.background = "#e2e8f0";
        statusPill.style.color = "#475569";
    }

    // Counts
    document.getElementById(`${lowerId}-recv-count`).textContent = procData.received.length;
    document.getElementById(`${lowerId}-pend-count`).textContent = procData.pending.length;
    document.getElementById(`${lowerId}-deliv-count`).textContent = procData.delivered.length;

    // 1. Received List (Arrivals)
    const recvListEl = document.getElementById(`${lowerId}-received-list`);
    if (procData.received.length === 0) {
        recvListEl.innerHTML = `<div class="empty-state">No arrivals yet</div>`;
    } else {
        recvListEl.innerHTML = procData.received.map(m => `
            <div class="packet-item">
                <div class="packet-info">
                    <span class="seq-tag">#${m.seq}</span>
                    <span class="packet-text" title="${escapeHtml(m.content)}">${escapeHtml(m.id)} (${escapeHtml(m.sender)})</span>
                </div>
                <span class="packet-meta">${m.arrival_delay_ms}ms</span>
            </div>
        `).join("");
    }

    // 2. Pending List (Waiting Queue)
    const pendListEl = document.getElementById(`${lowerId}-pending-list`);
    if (procData.pending.length === 0) {
        pendListEl.innerHTML = `<div class="empty-state">Queue is empty</div>`;
    } else {
        pendListEl.innerHTML = procData.pending.map(m => `
            <div class="packet-item pending-packet">
                <div class="packet-info">
                    <span class="seq-tag" style="background:#fed7aa; color:#9a3412;">#${m.seq}</span>
                    <span class="packet-text">${escapeHtml(m.id)}</span>
                </div>
                <span class="packet-meta" style="color:#c2410c;">Waiting for #${procData.expected_seq}</span>
            </div>
        `).join("");
    }

    // 3. Delivered List (Total Order Execution)
    const delivListEl = document.getElementById(`${lowerId}-delivered-list`);
    if (procData.delivered.length === 0) {
        delivListEl.innerHTML = `<div class="empty-state">Nothing delivered yet</div>`;
    } else {
        delivListEl.innerHTML = procData.delivered.map(m => `
            <div class="packet-item delivered-packet">
                <div class="packet-info">
                    <span class="seq-tag" style="background:#bbf7d0; color:#14532d;">#${m.seq}</span>
                    <span class="packet-text" title="${escapeHtml(m.content)}">${escapeHtml(m.id)}: ${escapeHtml(m.content)}</span>
                </div>
                <span class="packet-meta" style="color:#15803d;">✓ Delivered</span>
            </div>
        `).join("");
    }
}

/**
 * Hinglish: Timeline container mein simulation events display karta hai.
 */
let currentEventLogs = [];
function renderTimeline(logs) {
    if (!logs) return;
    currentEventLogs = logs;
    filterEventLogs(document.getElementById("log-filter").value);
}

function filterEventLogs(filterType) {
    const container = document.getElementById("timeline-container");
    if (!currentEventLogs || currentEventLogs.length === 0) {
        container.innerHTML = `<div class="empty-state">Waiting for simulation events...</div>`;
        return;
    }

    let filtered = currentEventLogs;
    if (filterType === "SEQUENCER") {
        filtered = currentEventLogs.filter(l => l.process_id === "SEQUENCER");
    } else if (filterType === "P1" || filterType === "P2" || filterType === "P3") {
        filtered = currentEventLogs.filter(l => l.process_id === filterType);
    } else if (filterType === "PENDING") {
        filtered = currentEventLogs.filter(l => l.type === "PENDING");
    } else if (filterType === "DELIVERED") {
        filtered = currentEventLogs.filter(l => l.type === "DELIVERED");
    }

    if (filtered.length === 0) {
        container.innerHTML = `<div class="empty-state">No events match filter '${filterType}'</div>`;
        return;
    }

    // Reverse order taaki latest event sabse upar dikhe
    const reversed = [...filtered].reverse();

    container.innerHTML = reversed.map(log => {
        let badgeClass = "badge-gray";
        let rowClass = "t-reset";

        if (log.type === "SUBMITTED") {
            badgeClass = "badge-blue"; rowClass = "t-submitted";
        } else if (log.type === "SEQUENCED") {
            badgeClass = "badge-indigo"; rowClass = "t-sequenced";
        } else if (log.type === "ARRIVED") {
            badgeClass = "badge-amber"; rowClass = "t-arrived";
        } else if (log.type === "PENDING") {
            badgeClass = "badge-orange"; rowClass = "t-pending";
        } else if (log.type === "DELIVERED") {
            badgeClass = "badge-green"; rowClass = "t-delivered";
        }

        return `
            <div class="timeline-row ${rowClass}">
                <span class="t-time">${log.timestamp}</span>
                <span class="t-badge ${badgeClass}">${log.type}</span>
                <span class="seq-tag" style="font-size:0.75rem;">${log.process_id}</span>
                <div class="t-desc">${escapeHtml(log.description)}</div>
            </div>
        `;
    }).join("");
}

function clearEventLogDisplay() {
    document.getElementById("timeline-container").innerHTML = `<div class="empty-state">Event log view cleared</div>`;
}

/**
 * Hinglish: Total Order property verify karta hai:
 * Backend /api/verify ko call karta hai aur visual comparison track render karta hai.
 */
async function checkTotalOrderVerification() {
    try {
        const response = await fetch("/api/verify");
        const data = await response.json();

        const badgeEl = document.getElementById("verif-status-badge");
        const expEl = document.getElementById("verif-explanation-text");

        // Delivery sequence tracks
        renderTrackSequence("p1-history-track", data.histories.P1);
        renderTrackSequence("p2-history-track", data.histories.P2);
        renderTrackSequence("p3-history-track", data.histories.P3);

        expEl.textContent = data.explanation;

        // Criteria checklist items
        const critMatch = document.getElementById("crit-match");
        const critMono = document.getElementById("crit-mono");
        const critPending = document.getElementById("crit-pending");

        if (data.status === "PASS") {
            badgeEl.className = "verif-large-badge badge-pass";
            badgeEl.textContent = "PASS";
            updateSystemStatus("Total Order Satisfied (PASS)", "badge-pass");

            setCriteriaItem(critMatch, true);
            setCriteriaItem(critMono, true);
            setCriteriaItem(critPending, true);
        } else if (data.status === "FAIL") {
            badgeEl.className = "verif-large-badge badge-fail";
            badgeEl.textContent = "FAIL";
            updateSystemStatus("Total Order Violated (FAIL)", "badge-danger");

            setCriteriaItem(critMatch, false);
            setCriteriaItem(critMono, false);
            setCriteriaItem(critPending, false);
        } else if (data.status === "IN_PROGRESS") {
            badgeEl.className = "verif-large-badge badge-progress";
            badgeEl.textContent = "IN PROGRESS";
            updateSystemStatus("Transit In Progress...", "badge-simulating");

            setCriteriaItem(critMatch, true);
            setCriteriaItem(critMono, true);
            setCriteriaItem(critPending, false);
        } else {
            // EMPTY / READY
            badgeEl.className = "verif-large-badge badge-neutral";
            badgeEl.textContent = "READY";
            updateSystemStatus("Ready / Idle", "badge-idle");

            resetCriteriaItem(critMatch);
            resetCriteriaItem(critMono);
            resetCriteriaItem(critPending);
        }
    } catch (err) {
        console.error("Verification fetch error:", err);
    }
}

function renderTrackSequence(elementId, history) {
    const el = document.getElementById(elementId);
    if (!history || history.length === 0) {
        el.innerHTML = `<span class="empty-tag">[Empty - No messages delivered yet]</span>`;
        return;
    }

    el.innerHTML = history.map((item, index) => {
        const arrow = index < history.length - 1 ? `<span class="track-arrow">➔</span>` : "";
        return `<span class="track-pill">${escapeHtml(item)}</span>${arrow}`;
    }).join("");
}

function setCriteriaItem(itemEl, isSuccess) {
    if (isSuccess) {
        itemEl.className = "crit-item crit-pass";
        itemEl.querySelector(".crit-icon").textContent = "✓";
    } else {
        itemEl.className = "crit-item crit-fail";
        itemEl.querySelector(".crit-icon").textContent = "✗";
    }
}

function resetCriteriaItem(itemEl) {
    itemEl.className = "crit-item";
    itemEl.querySelector(".crit-icon").textContent = "⚪";
}

/**
 * Hinglish: Global system status badge update karta hai.
 */
function updateSystemStatus(text, badgeClass) {
    const badge = document.getElementById("system-status-badge");
    badge.textContent = text;
    badge.className = `badge ${badgeClass}`;
}

/**
 * Hinglish: Simulation ko poori tarah reset karta hai.
 * Active timers clear karta hai aur backend state reset karwata hai.
 */
async function handleResetSimulation() {
    // 1. Sabhi active JavaScript timers clear karo
    activeTransitTimers.forEach(id => clearTimeout(id));
    activeTransitTimers = [];
    pausedQueue = [];
    isSimulationPaused = false;
    document.getElementById("pause-icon").textContent = "⏸";
    document.getElementById("pause-text").textContent = "Pause Transit";

    try {
        const response = await fetch("/api/reset", { method: "POST" });
        const data = await response.json();
        if (data.success) {
            showFeedback("Simulation reset successfully. All counters and buffers cleared.", "success");
            renderDashboard(data.state);
            checkTotalOrderVerification();
        }
    } catch (err) {
        console.error("Reset error:", err);
    }
}

/**
 * Hinglish: Transit ko pause ya resume karta hai.
 */
function togglePauseSimulation() {
    isSimulationPaused = !isSimulationPaused;
    const icon = document.getElementById("pause-icon");
    const text = document.getElementById("pause-text");

    if (isSimulationPaused) {
        icon.textContent = "▶";
        text.textContent = "Resume Transit";
        showFeedback("Simulation transit paused. Incoming packets held.", "error");
    } else {
        icon.textContent = "⏸";
        text.textContent = "Pause Transit";
        showFeedback("Simulation resumed. Releasing paused packets...", "success");

        // Paused queue ke packets ko dispatch karo
        const toRelease = [...pausedQueue];
        pausedQueue = [];
        toRelease.forEach(item => {
            dispatchArrival(item.procId, item.messageId, item.delayMs);
        });
    }
}

/**
 * Hinglish: Random delay mode toggle switch handler.
 */
function toggleRandomDelayMode(event) {
    isRandomDelayEnabled = event.target.checked;
    const manualPanel = document.getElementById("manual-delays-panel");
    const desc = document.getElementById("delay-mode-desc");

    if (isRandomDelayEnabled) {
        manualPanel.style.opacity = "0.4";
        manualPanel.style.pointerEvents = "none";
        desc.textContent = "Enabled: Random network jitter (400ms - 3500ms per node)";
        showFeedback("Random Delay Mode Enabled! Packets will arrive out-of-order.", "success");
    } else {
        manualPanel.style.opacity = "1";
        manualPanel.style.pointerEvents = "auto";
        desc.textContent = "Disabled: Manual delay values configured below";
        showFeedback("Manual Delay Mode Active.", "success");
    }
}

/**
 * Hinglish: Manual slider ki value update karta hai.
 */
function updateDelayDisplay(proc, value) {
    const label = document.getElementById(`delay-val-${proc}`);
    if (label) {
        label.textContent = `${value} ms`;
    }
}

/**
 * Hinglish: Quick academic preset scenarios run karta hai:
 * 1. in_order: Synchronous equal delays
 * 2. out_of_order: P2 ko Msg 2 pehle milta hai, Msg 1 baad mein (Buffer hold demo)
 * 3. high_jitter: Asymmetric delay scramble
 */
async function loadSampleScenario(scenarioKey) {
    await handleResetSimulation();

    const delayToggle = document.getElementById("random-delay-toggle");

    if (scenarioKey === "in_order") {
        delayToggle.checked = false;
        toggleRandomDelayMode({ target: delayToggle });
        document.getElementById("delay-p1").value = 600;
        document.getElementById("delay-p2").value = 600;
        document.getElementById("delay-p3").value = 600;
        updateDelayDisplay("p1", 600);
        updateDelayDisplay("p2", 600);
        updateDelayDisplay("p3", 600);

        showFeedback("Running Scenario 1: Basic Synchronous In-Order Delivery...", "success");
        await sendSampleMessage("Alice", "Init Transaction A (Seq #1)");
        setTimeout(() => sendSampleMessage("Bob", "Process Payment B (Seq #2)"), 400);
        setTimeout(() => sendSampleMessage("Charlie", "Commit Audit C (Seq #3)"), 800);

    } else if (scenarioKey === "out_of_order") {
        delayToggle.checked = false;
        toggleRandomDelayMode({ target: delayToggle });

        showFeedback("Running Scenario 2: Out-of-Order Arrival Demo! Observe P2's Pending Buffer.", "success");

        // Message 1: P2 gets high delay (2800ms)
        const msg1 = await sendSampleMessageDirect("Alice", "Deposit $500 (Seq #1)");
        if (msg1) {
            multicastMessageToProcesses(msg1, { P1: 800, P2: 2800, P3: 800 });
        }

        // Message 2: P2 gets low delay (800ms) -> Msg 2 arrives at P2 BEFORE Msg 1!
        setTimeout(async () => {
            const msg2 = await sendSampleMessageDirect("Bob", "Withdraw $200 (Seq #2)");
            if (msg2) {
                multicastMessageToProcesses(msg2, { P1: 1400, P2: 800, P3: 1400 });
            }
        }, 300);

        // Message 3
        setTimeout(async () => {
            const msg3 = await sendSampleMessageDirect("Charlie", "Final Balance Check (Seq #3)");
            if (msg3) {
                multicastMessageToProcesses(msg3, { P1: 2000, P2: 3200, P3: 2000 });
            }
        }, 600);

    } else if (scenarioKey === "high_jitter") {
        delayToggle.checked = true;
        toggleRandomDelayMode({ target: delayToggle });

        showFeedback("Running Scenario 3: High Network Jitter! Random arrival times across all nodes.", "success");
        await sendSampleMessage("Alice", "Broadcast Alpha");
        setTimeout(() => sendSampleMessage("Bob", "Broadcast Beta"), 250);
        setTimeout(() => sendSampleMessage("Charlie", "Broadcast Gamma"), 500);
    }
}

async function sendSampleMessage(sender, content) {
    try {
        const response = await fetch("/api/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sender, content })
        });
        const data = await response.json();
        if (data.success) {
            fetchSimulationState();
            multicastMessageToProcesses(data.message);
        }
    } catch (e) {
        console.error(e);
    }
}

async function sendSampleMessageDirect(sender, content) {
    try {
        const response = await fetch("/api/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sender, content })
        });
        const data = await response.json();
        if (data.success) {
            fetchSimulationState();
            return data.message;
        }
    } catch (e) {
        console.error(e);
    }
    return null;
}

/**
 * Hinglish: Inline feedback message show karta hai (success / error).
 */
function showFeedback(text, type = "success") {
    const banner = document.getElementById("composer-feedback");
    banner.textContent = text;
    banner.className = `feedback-banner feedback-${type}`;
    banner.classList.remove("hidden");

    setTimeout(() => {
        banner.classList.add("hidden");
    }, 4500);
}

/**
 * Hinglish: XSS attacks se bachne ke liye text ko escape karta hai.
 */
function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
