const port = chrome.runtime.connect({ name: "sidepanel" });

const statusIndicator = document.getElementById('status-indicator');
const statusText = document.getElementById('status-text');
const logContainer = document.getElementById('log-container');
const agentStatus = document.getElementById('agent-active-status');
const actionDisplay = document.getElementById('current-action-display');
const screenshotPreview = document.getElementById('screenshot-preview');
const agentChat = document.getElementById('agent-chat');
const agentMessageText = document.getElementById('agent-message-text');

// Check connection status on load
port.postMessage({ type: "check_status" });

port.onMessage.addListener((msg) => {
    if (msg.type === "socket_status") {
        updateStatus(msg.connected);
    } else if (msg.type === "agent_status") {
        addLog(msg.message, "status");
    } else if (msg.type === "agent_response") {
        handleAgentResponse(msg.data);
    } else if (msg.type === "observation_update") {
        if (msg.data.screenshot) {
            screenshotPreview.src = msg.data.screenshot;
        }
    } else if (msg.type === "agent_message") {
        agentChat.style.display = "block";
        agentMessageText.innerText = msg.text;
        addLog(`[MESSAGE] ${msg.text}`, "info");
    }
});

function updateStatus(connected) {
    if (connected) {
        statusIndicator.classList.add('status-connected');
        statusText.innerText = "Connected";
        agentStatus.style.display = "block";

        // AUTO-START: Tell the Brain we are ready on this tab
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
            if (tabs[0]) {
                port.postMessage({
                    type: "start_agent",
                    tabId: tabs[0].id,
                    query: "Autonomous Observation",
                    model: "antigravity"
                });
            }
        });
    } else {
        statusIndicator.classList.remove('status-connected');
        statusText.innerText = "Disconnected";
        agentStatus.style.display = "none";
    }
}

function addLog(message, type = "info") {
    const entry = document.createElement('div');
    entry.className = `log-entry log-${type}`;

    if (type === "thought") {
        entry.innerHTML = `<span class="log-thought">${message}</span>`;
    } else {
        entry.innerText = message;
    }

    logContainer.prepend(entry);
}

function handleAgentResponse(data) {
    if (data.thought) {
        addLog(data.thought, "thought");
    }

    if (data.action) {
        const actionLabels = {
            "click": `Clicking: ${data.payload.selector}`,
            "type": `Typing into: ${data.payload.selector}`,
            "inject_js": "Injecting Diagnostic Script...",
            "post_message": "Messaging User...",
            "run_test": "Running Verification Test...",
            "inspect_element": `Inspecting: ${data.payload.selector}`,
            "scroll": `Scrolling ${data.payload.y}px`,
            "navigate": `Navigating to: ${data.payload.url}`,
            "hover": `Hovering: ${data.payload.selector}`,
            "observe": "Observing page state...",
            "get_network_body": `Fetching Network Body: ${data.payload.url}`,
            "clear_site_data": "Clearing Site Data & Cookies..."
        };
        const label = actionLabels[data.action] || `TS Sidekick V2: ${data.action}`;
        addLog(label, "status");
        actionDisplay.innerText = label;

        // Hide chat when a new action starts, unless it's a message
        if (data.action !== "post_message" && data.action !== "answer_user") {
            agentChat.style.display = "none";
        }
    }
}
