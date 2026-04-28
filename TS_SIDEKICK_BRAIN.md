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
- `click(selector)`: Clicks element. Element will glow **Green** in the next screenshot for verification.
- `type(selector, text)`: Inputs text.
- `scroll(x, y)`: Navigates page. `x` and `y` are relative offsets.
- `hover(selector)`: Triggers hover. Element will have an **Orange dashed border** in the screenshot.
- `navigate(url)`: Hard navigation.
- `inject_js(code, world)`: Run custom logic. Use `MAIN` for shop variables, `ISOLATED` for UI/DOM.
- `inject_css(css)`: Modify page styles.
- `observe()`: Request a fresh screenshot/data.
- `answer_user(message)`: Final response to user. Stops the autopilot loop. DO NOT USE THIS WILLY-NILLY. ASK user first before using this.
- `get_network_body(url)`: Retrieve full response body of a captured request.
- `clear_site_data(url)`: Wipes cookies, cache, and localStorage for the origin.
- `select(selector, value)`: **Workaround**: Use `type(selector, value)` on `<select>` elements. The extension will update the value and dispatch `change` events.

- `capture_element(selector)`: Takes a targeted high-res screenshot of a specific element.
- `click_at_position(x, y)`: Clicks at specific coordinates.
- `get_computed_style(selector, properties)`: Retrieves specific CSS properties (e.g. `["display", "color"]`).

## 🔄 Verification & Self-Correction Loop
Every time the agent performs an action (like `inject_js` or `click`), the following happens:
1. **Execution:** The script/action is applied to the tab.
2. **Re-Observation:** The extension waits 2.5 seconds and then captures a **new screenshot** and **new console logs**.
3. **Feedback:** The agent reads the new state. If a script failed, the error will appear in the `console` field of `brain_input.json`.
4. **Correction:** If the agent sees an error or doesn't see the expected visual change in `current_view.png`, it must refine its script and try again.

## 📡 Re-starting the Autopilot
If the agent is not responding, run this command to start the Watchdog:
`powershell -Command "while(!(Test-Path server/brain_input.json)){Start-Sleep -Seconds 1}"`

## 🧩 Technical Schema (Antigravity Brain Protocol)

The Brain must write to `server/brain_output.json` using this exact structure:

```json
{
  "action": "inject_js" | "click" | "type" | "navigate" | "scroll" | "hover" | "observe" | "answer_user" | "get_network_body" | "clear_site_data" | "capture_element" | "click_at_position" | "get_computed_style",
  "payload": {
    "code": "javascript_code_here",
    "code_file": "optional_filename_on_server.js",
    "selector": "css_selector",
    "properties": ["display", "color"],
    "text": "input_text",
    "url": "target_url",

    "x": 0,
    "y": 500,
    "css": ".my-class { display: none; }",
    "world": "MAIN" | "ISOLATED"
  }
}
```

### 📡 The Observation Schema (brain_input.json)
The Brain receives data in this format:
- `dom`: String representation of interactive elements.
- `url`: Current page URL.
- `console`: Recent logs (includes `>>> NETWORK_BODY` and `🔍 ELEMENT CAPTURED`).
- `network`: List of requests (✅ SUCCESS / 🚨 FAILED).
- `screenshot`: Base64 PNG of the full viewport.
- `element_view`: `{ selector, data, x, y, w, h, dpr }` (Only present after `capture_element`).

### 🛡️ Deep Isolation Strategies

- **Zero-State Testing**: Use `clear_site_data()` + `navigate()` to verify how the shop looks to a brand new visitor.
- **Pixel-Perfect Audit**: Use `capture_element()` to verify UI details that might be too small in the main screenshot.

### ⚠️ Critical Communication Rules:
1.  **JSON Formatting:** Always write the output as a **single-line JSON** or ensure all newlines in code strings are escaped as `\n`. Multi-line literal strings will break the server's `json.load()`.
2.  **Data Extraction:** Since the bridge is reactive, use `console.log('>>> KEY: ' + value)` within `inject_js` to send data back. The Brain will find this in the `console` field of the next `brain_input.json`.
3.  **Execution Worlds & CSP:** 
    - Use `world: "MAIN"` if you need to access page-level variables (like `Shopify`). 
    - **Warning**: Sites with strict Content Security Policies (CSP) may block `inject_js` if it involves `eval()` or certain inline scripts. If `inject_js` returns an `EvalError` in the console, fallback to atomic actions (`click`, `type`, `scroll`) or DOM inspection.
4.  **Network Inspection:** 
    - **Automatic:** The extension proactively captures snippets (first 300 chars) of requests containing `/api/`, `.json`, or `cart`. Check the `network` field first.
    - **Manual:** Use `get_network_body` for the full content. The result will appear in the `console` field as a JSON string starting with `[console] >>> NETWORK_BODY:`.
5.  **Navigation Resilience:** The extension automatically re-attaches the debugger and re-injects the sidekick script upon page navigation. However, any manual monkey-patches (like `fetch` overrides) must be re-applied by the agent on the new page.
7.  **Visual Self-Verification:** The AI should look for **Green outlines** (clicks) or **Orange dashed borders** (hovers) in `current_view.png` to confirm the extension targeted the correct element.
8.  **Timing & Heartbeat:** 
    - The extension waits 2.5s after an action before capturing the next observation. 
    - Monitor `server/heartbeat.txt` (updated every ~10s) to confirm the Python bridge is running if the terminal logs appear "stuck".
    - The server (`main.py`) has a **5-retry loop** for reading `brain_output.json` to prevent race conditions.
9.  **Credentials:**
    - Shopify Password: `builtbyjall` (for `built-by-jall.myshopify.com`).

## Key Files:
- `extension/service_worker.js`: The "Body" (Handles debugger, screenshots, and WebSocket).
- `server/main.py`: The "Bridge" (FastAPI server + file tunnel).
- `extension/sidepanel/ui.html`: The "Dashboard" (Read-only status monitor).
- `server/current_view.png`: The "Eyes" (Latest screenshot of the tab).

