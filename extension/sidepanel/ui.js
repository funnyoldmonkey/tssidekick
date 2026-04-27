const port = chrome.runtime.connect({ name: "sidepanel" });

const statusIndicator = document.getElementById('status-indicator');
const statusText = document.getElementById('status-text');
const logContainer = document.getElementById('log-container');
const agentStatus = document.getElementById('agent-active-status');
const actionDisplay = document.getElementById('current-action-display');

// Check connection status on load
port.postMessage({ type: "check_status" });

port.onMessage.addListener((msg) => {
    if (msg.type === "socket_status") {
        updateStatus(msg.connected);
    } else if (msg.type === "agent_status") {
        addLog(msg.message, "status");
    } else if (msg.type === "agent_response") {
        handleAgentResponse(msg.data);
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
            "answer_user": "[OK] Task Complete",
            "scroll": `Scrolling ${data.payload.y}px`,
            "navigate": `Navigating to: ${data.payload.url}`,
            "hover": `Hovering: ${data.payload.selector}`,
            "observe": "Observing page state..."
        };
        const label = actionLabels[data.action] || "TS Sidekick is acting...";
        addLog(label, "status");
        actionDisplay.innerText = label;
    }
}
