# TS Sidekick: Architecture & Antigravity Brain Protocol (Avatar Mode)

## Project Overview
TS Sidekick is a high-performance troubleshooting extension with a Python sidecar. It operates in **Avatar Mode**, where the Antigravity AI Agent uses the browser extension as its remote-controlled "hands and eyes" within the user's actual browser session.

## 🤖 The Avatar Interaction Model
Unlike standard agents, TS Sidekick does not have its own conversation UI. The user interacts with the Brain (Antigravity AI) directly in the coding chat.

### The Handshake Protocol:
1. **Bridge Initialization:** The user runs `start.bat`. The server launches into the **System Tray** (look for the "TS" icon).
2. **Avatar Activation:** User opens the TS Sidekick sidepanel in Chrome.
3. **Observation:** The extension captures DOM, Console Logs, Network Data, and a **Screenshot**.
4. **Tunneling:** `main.py` writes the data to `server/brain_input.json` and saves the screenshot to `server/current_view.png`.
5. **Autopilot Loop:** The AI Agent reads the observation, views the screenshot, decides on an action, and writes to `server/brain_output.json`.
6. **Execution:** The server pushes the action to the extension, which executes it in the active tab.

## 🛠️ Supported Actions (Avatar Capabilities)
The agent can perform the following actions:
- `click(selector)`: Click elements.
- `type(selector, text)`: Input text into fields.
- `scroll(x, y)`: Navigate long pages.
- `hover(selector)`: Trigger mouse-over events.
- `navigate(url)`: Change the page.
- `inject_js(code)`: Run custom diagnostics (e.g., Deep Scans).
- `inject_css(css)`: Modify page styles/layout.
- `answer_user(message)`: Report findings back to the chat.

## 🔄 Verification & Self-Correction Loop
Every time the agent performs an action (like `inject_js` or `click`), the following happens:
1. **Execution:** The script/action is applied to the tab.
2. **Re-Observation:** The extension waits 2.5 seconds and then captures a **new screenshot** and **new console logs**.
3. **Feedback:** The agent reads the new state. If a script failed, the error will appear in the `console` field of `brain_input.json`.
4. **Correction:** If the agent sees an error or doesn't see the expected visual change in `current_view.png`, it must refine its script and try again.

## 📡 Re-starting the Autopilot
If the agent is not responding, run this command to start the Watchdog:
`powershell -Command "while(!(Test-Path server/brain_input.json)){Start-Sleep -Seconds 1}"`

## Key Files:
- `extension/service_worker.js`: The "Body" (Handles debugger, screenshots, and WebSocket).
- `server/main.py`: The "Bridge" (FastAPI server + file tunnel).
- `extension/sidepanel/ui.html`: The "Dashboard" (Read-only status monitor).
- `server/current_view.png`: The "Eyes" (Latest screenshot of the tab).
