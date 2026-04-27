# 🚀 TS Sidekick: Avatar Mode Troubleshooting

TS Sidekick is a high-performance troubleshooting browser extension powered by a Python sidecar. It operates in **Avatar Mode**, enabling an AI agent (Antigravity) to use the browser as its remote-controlled "hands and eyes" to diagnose and fix issues directly within your active session.

## 🤖 The Avatar Interaction Model

Unlike traditional AI assistants, TS Sidekick provides the bridge between your local environment and the AI Brain.

1.  **Bridge Initialization**: Run `start.bat` to launch the Python server (FastAPI). It sits in your system tray (look for the green "TS" icon).
2.  **Avatar Activation**: Open the TS Sidekick sidepanel in Chrome.
3.  **Observation**: The extension captures the DOM, Console Logs, Network Data, and a high-res Screenshot.
4.  **Tunneling**: Data is tunneled to the local server via WebSocket and file-based communication (`brain_input.json`).
5.  **Autopilot Loop**: The AI Agent reads the observation, views the screenshot, and decides on an action.
6.  **Execution**: The server pushes actions (clicks, typing, scripts) back to the extension to execute in real-time.

## 🛠️ Avatar Capabilities

The agent can perform complex browser interactions:
*   **Interaction**: Click, Type, Scroll, Hover, Navigate.
*   **Diagnostic**: Inject custom JavaScript (Deep Scans) and CSS modifications.
*   **Feedback**: Reports findings directly back to your coding chat.

## 🔄 Self-Correction Loop

Every action is verified through a feedback loop:
1.  **Action**: The AI sends a command (e.g., `inject_js`).
2.  **Wait**: The extension waits ~2.5s for the UI to update.
3.  **Verify**: A new screenshot and set of console logs are captured.
4.  **Correct**: The AI compares the new state with the intended goal and corrects itself if necessary.

## 📂 Project Structure

*   `extension/`: The Chrome extension (Service Worker, Sidepanel UI, and Content Scripts).
*   `server/`: Python FastAPI sidecar bridge handling WebSockets and the "Brain Tunnel".
*   `TS_SIDEKICK_BRAIN.md`: Core logic and interaction protocol documentation.

## 🚦 Getting Started

### Prerequisites
*   Python 3.8+
*   Google Chrome (for the extension)

### Installation

1.  **Clone the Repository**:
    ```bash
    git clone https://github.com/funnyoldmonkey/tssidekick.git
    cd tssidekick
    ```

2.  **Install Server Dependencies**:
    ```bash
    pip install fastapi uvicorn pystray Pillow
    ```

3.  **Load the Extension**:
    *   Open Chrome and go to `chrome://extensions/`.
    *   Enable **Developer mode**.
    *   Click **Load unpacked** and select the `extension/` folder.

4.  **Launch the Bridge**:
    *   Run `start.bat` from the root directory.
    *   Verify the server is running by checking the system tray icon.

## 📡 Watchdog (Manual Recovery)
If the agent stops responding, you can manually trigger the observation cycle using:
```powershell
powershell -Command "while(!(Test-Path server/brain_input.json)){Start-Sleep -Seconds 1}"
```

---
*Built with ❤️ for high-performance support engineering.*
