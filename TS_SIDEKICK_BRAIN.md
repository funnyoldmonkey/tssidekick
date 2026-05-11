# TS Sidekick V2: Elite Autonomous Brain Protocol

## Project Overview
TS Sidekick V2 is an autonomous troubleshooting agent that operates in a continuous loop. It prioritizes **Visual Verification** and **Test-Driven Fixing**.

## 🤖 The V2 Interaction Model
1. **Bridge Initialization:** Run `start.bat`.
2. **Observation:** Extension captures high-res screenshot, full logs, and skeletal DOM.
3. **Reasoning:** AI analyzes state, checks for truncation, and plans a fix.
4. **Verification Loop:** 
   - AI performs action.
   - Extension waits 2.5s and re-observes.
   - AI verifies the fix via `inspect_element` or `run_test`.
   - If failed, AI retries autonomously.
5. **Continuous Conversation:** AI communicates via `post_message`. The loop stays active for follow-ups.

## 🛠️ V2 Actions (Avatar Capabilities)
- `click(selector)`: Element glows **Green** for visual confirmation.
- `type(selector, text)`: Input text + change event dispatch.
- `scroll(x, y)`: Relative scroll.
- `hover(selector)`: Element border turns **Orange dashed**.
- `navigate(url)`: Hard navigation.
- `inject_js(code)`: Debugger-level injection (bypasses CSP).
- `run_test(code)`: Executes a test script. Returns `{ success: bool, message: string }`.
- `inspect_element(selector)`: Returns full computed styles, attributes, and box rect.
- `observe()`: Request fresh observation.
- `post_message(message)`: Send update to user. Does NOT stop the loop.
- `get_network_body(url)`: Retrieve full response body.
- `clear_site_data(url)`: Wipe storage/cookies.
- `capture_element(selector)`: Targeted high-res screenshot.

## 📡 The Observation Schema (brain_input.json)
- `dom`: Actionable Markdown. No truncation of interactive elements.
- `url`: Current page URL.
- `console`: Last 1000 logs. Look for `>>> TEST_RESULT` or `>>> INSPECT`.
- `network`: Last 1000 requests.
- `screenshot_path`: Path to the latest `sessions/{tab_id}/view_{ts}.png`.
- `element_view`: High-res crop if `capture_element` was used.

## ⚠️ Critical Communication Rules:
1.  **Always Verify**: Never assume a fix worked. Use `inspect_element` or `run_test` to confirm.
2.  **Vision is Key**: Check the screenshot for green/orange indicators to ensure you clicked the right thing.
3.  **No Truncation Fear**: Interactive elements are no longer truncated. If you need deep details on a non-interactive node, use `inspect_element`.
4.  **Continuous Loop**: The agent will keep running until the user closes the sidepanel. If you are waiting for user input, just use `post_message` and then `observe` (or wait).

## Technical Schema (JSON Output)
```json
{
  "thought": "Reasoning including verification steps.",
  "action": "click" | "type" | "inject_js" | "navigate" | "scroll" | "hover" | "post_message" | "observe" | "run_test" | "inspect_element" | "get_network_body" | "clear_site_data" | "capture_element",
  "payload": {
    "selector": "css_selector",
    "text": "text",
    "code": "js_code",
    "url": "url",
    "message": "message_to_user"
  }
}
```

