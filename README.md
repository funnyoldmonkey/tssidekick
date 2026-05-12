# TS Sidekick V2

An autonomous Tier 2 support agent that uses a Chrome extension as its eyes and hands, and an AI model as its brain. It diagnoses browser issues in real time, fixes them via JavaScript/CSS injection, verifies the fix, and delivers the working code — all without manual intervention.

Built for support engineers who troubleshoot live websites (Shopify, WordPress, Wix, Squarespace, and more).

## How It Works

TS Sidekick operates as a bridge between a browser tab and an AI IDE. The Chrome extension captures everything happening on the page — DOM, console logs, network requests, screenshots — and streams it to a local Python server. The server packages the data and hands it to the AI brain (your IDE), which diagnoses the issue, injects fixes, and verifies results in a continuous loop.

```
┌──────────────┐     WebSocket     ┌──────────────┐     File I/O     ┌──────────────┐
│   Chrome     │ ◄──────────────► │   Python     │ ◄──────────────► │   AI IDE     │
│  Extension   │   observations   │   Server     │  brain_input.json │ (OpenCode,   │
│  (eyes/hands)│   + actions      │  (sidecar)   │  brain_output.json│  Cursor, etc)│
└──────────────┘                  └──────────────┘                  └──────────────┘
```

**The loop:**
1. Extension captures a full observation (DOM, console, network, screenshot)
2. Server writes slim summary to `brain_input.json`, full data to `scratch/` files
3. AI IDE reads the observation, decides on an action, writes to `brain_output.json`
4. Server reads the action and routes it — either to the extension (browser actions) or handles it locally (search/diagnose actions)
5. Extension executes the action (click, inject JS, navigate, etc.)
6. Wait 2.5 seconds for the page to settle, then re-capture and loop back to step 1

## Quick Start

### Prerequisites

- Python 3.8+
- Google Chrome
- An AI IDE that supports file-based communication (OpenCode, Cursor, Windsurf, or similar)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/funnyoldmonkey/tssidekick.git
   cd tssidekick2
   ```

2. **Install server dependencies:**
   ```bash
   cd server
   pip install fastapi uvicorn websockets python-dotenv Pillow pystray
   ```

3. **Load the Chrome extension:**
   - Open `chrome://extensions/`
   - Enable **Developer mode**
   - Click **Load unpacked** and select the `extension/` folder

### First Run

1. **Launch the server** — Run `start.bat` from the root directory. A green "TS" icon appears in your system tray. The server is now listening on `ws://127.0.0.1:8000`.

2. **Open the extension** — In Chrome, navigate to the page you want to troubleshoot. Click the TS Sidekick extension icon to open the sidepanel.

3. **Connect the extension** — In the sidepanel, select "Antigravity" as the mode. Enter a brief description of the issue (or just "ready"). Click **Start**. The extension attaches to your active tab and begins capturing observations. You'll see a green glow on the page confirming the debugger is attached.

4. **Feed the brain to your IDE** — In your AI IDE, reference `TS_SIDEKICK_BRAIN.md`. This is the agent's playbook — it tells the AI what tools it has, how to diagnose, and how to fix issues. On first load, the AI will read the brain file and `brain_input.json`, then greet you with the site name and wait for your concern.

5. **Describe the issue** — Tell the AI what's wrong (e.g., "The Add to Cart button doesn't work" or "The chat widget isn't showing"). The AI will begin its autonomous diagnostic loop: diagnose → investigate → fix → verify → deliver the working code.

6. **Review the fix** — Once the AI verifies its fix, it delivers the root cause, the working code, and instructions on where to implement it permanently.

## Key Features

### Cross-Reference Diagnostic Engine

The `diagnose()` action runs entirely server-side and pre-correlates data across all sources:

- **Script analysis** — Finds every external and inline script, cross-references each against network logs to determine if it loaded successfully, and links scripts to their console errors by domain
- **Hidden element detection** — Flags elements hidden by `display:none`, `visibility:hidden`, `opacity:0`, or zero dimensions
- **Platform detection** — Auto-detects Shopify, WordPress, Wix, Squarespace, Webflow, Magento, and BigCommerce from DOM markers
- **Scenario auto-detection** — Scores signals across 8 scenario types and recommends the right troubleshooting playbook
- **Shopify-specific context** — Detects app blocks, product forms, cart forms, and common app containers
- **Third-party embed detection** — Identifies 25+ services (Intercom, Drift, Stripe, Facebook, Google Analytics, etc.) and reports their load status
- **Form analysis** — Finds all forms, checks for disabled inputs, missing CSRF tokens, and hidden required fields
- **Auth signal detection** — Catches 401/403 errors, expired tokens, and OAuth issues from both console and network

### Scenario Playbooks

The diagnostic engine auto-detects which playbook to follow:

| Scenario | Triggers On |
|---|---|
| **WIDGET_NOT_SHOWING** | Hidden elements, failed script loads |
| **SHOPIFY_APP** | Shopify platform + app scripts detected |
| **FORM_SUBMISSION** | Forms present + submission errors |
| **API_NETWORK_ERROR** | Multiple 4xx/5xx failures, CORS errors |
| **CSS_LAYOUT** | Hidden elements, visual breakage signals |
| **AUTH_SESSION** | 401/403 errors, token/session failures |
| **THIRD_PARTY_EMBED** | Broken third-party scripts with errors |
| **GENERAL** | Fallback when no specific scenario scores high |

### Fix-and-Verify Loop

The agent doesn't just apply a fix and hope — it verifies:

1. Injects the fix via `inject_js` or `inject_css` (bypasses CSP via Chrome Debugger Protocol)
2. Waits for the page to update, captures a fresh observation
3. Checks the screenshot, searches the DOM, and inspects element styles to confirm
4. If the fix didn't work, reviews its previous attempts and tries a different approach
5. After 3 failed attempts, escalates to the user with root cause analysis and what was tried

All fix attempts are tracked with code previews so the AI never repeats a failed approach.

### Fix Delivery

Once a fix is verified, the agent delivers:
- Root cause explanation
- The exact working code in a clean, copy-paste-ready block
- Instructions on where to implement permanently (e.g., theme.liquid, custom CSS section, app settings)
- Screenshot confirmation

### Server-Side Search Tools

Full observation data is written to `scratch/` files with no truncation. The AI searches these files instantly without roundtripping to the extension:

| Tool | What It Does |
|---|---|
| `diagnose()` | Full cross-reference analysis + scenario detection |
| `search_dom(query)` | Grep the full DOM capture |
| `search_console(query)` | Grep all console logs |
| `search_network(query)` | Grep all network requests |
| `read_network_body(filename)` | Read the full response body of any captured request |
| `refresh_files` | Force a fresh observation cycle |

### Browser Actions

Actions routed to the extension for real-time execution:

| Action | Description |
|---|---|
| `click(selector)` | Click with green glow confirmation |
| `type(selector, text)` | Type text with event dispatch |
| `scroll(x, y)` | Relative scroll |
| `hover(selector)` | Hover with orange dashed border indicator |
| `navigate(url)` | Hard navigation |
| `inject_js(code)` | Debugger-level JS injection (bypasses CSP) |
| `inject_css(css)` | Insert CSS stylesheet |
| `run_test(code)` | Execute test code, returns success/failure |
| `inspect_element(selector)` | Full computed styles, attributes, bounding rect |
| `observe()` | Trigger fresh observation cycle |
| `post_message(message)` | Send notification to sidepanel |
| `get_network_body(url)` | Fetch response body via debugger |
| `clear_site_data(url)` | Wipe cookies, storage, and cache |
| `capture_element(selector)` | High-res screenshot of a specific element |

### Resilient Selector Strategy

The agent uses portable, platform-agnostic selectors that work across any store or site — never template-specific IDs that break when themes change. Selector priority:

1. Role/attribute selectors: `form[action*="/cart/add"]`, `button[name="add"]`
2. Semantic class selectors: `.product-form__submit`, `.product-form`
3. Data attribute selectors: `[data-add-to-cart]`, `[data-type="add-to-cart-form"]`
4. Tag + context selectors: `product-form button[type="submit"]`

### Context Management

- **Slim observations** for brain_input.json — element counts, error counts, last 20 console/network lines, first 30 interactive elements
- **Full data** in scratch files — no truncation, searchable on demand
- **History trimming** — Caps conversation history at 20 turns to prevent free-tier context overflow
- **Fix attempt tracking** — Stores all previous inject_js/inject_css attempts with code previews

## Architecture

```
tssidekick2/
├── extension/                  # Chrome Extension (Manifest V3)
│   ├── manifest.json           # Permissions: debugger, sidePanel, scripting, etc.
│   ├── service_worker.js       # Core: WebSocket, debugger, observation capture, action execution
│   ├── sidepanel/
│   │   ├── ui.html             # Sidepanel UI
│   │   └── ui.js               # Sidepanel logic and status display
│   └── scripts/
│       ├── content.js          # Content script (page-level bridge)
│       └── actions.js          # Action injection helpers
├── server/                     # Python Sidecar (FastAPI)
│   ├── main.py                 # WebSocket server, diagnostic engine, brain tunnel, system tray
│   └── check_image.py          # Screenshot validation utility
├── scratch/                    # Full observation data (gitignored)
│   ├── obs_dom.txt             # Complete DOM capture
│   ├── obs_console.log         # All console logs
│   ├── obs_network.log         # All network requests
│   └── obs_net_bodies/         # Individual API response bodies
├── TS_SIDEKICK_BRAIN.md        # AI Brain protocol and playbooks
├── start.bat                   # One-click launcher
└── README.md
```

## Observation Data Format

### DOM Capture (`scratch/obs_dom.txt`)
```
★ [button.product-form__submit] "ADD TO CART"       # ★ = interactive element
· [div.product-description] "An ivory linen..."      # · = non-interactive element
📜 [script] src="https://cdn.shopify.com/..."         # 📜 = script tag
🎨 [link rel="stylesheet"] href="/assets/theme.css"   # 🎨 = style/link tag
★ [input.quantity-input] [HIDDEN:display] ""          # [HIDDEN:reason] = visibility flag
```

### Network Capture (`scratch/obs_network.log`)
```
✅ 200 GET https://cdn.shopify.com/s/files/1/theme.js
🚨 FAILED 404 GET https://app.example.com/widget.js
📦 DATA [widget.js] (2.3 KB)
```

## Tech Stack

- **Chrome Extension**: Manifest V3, Chrome Debugger Protocol 1.3 (Network.enable, Log.enable, Runtime.enable, Runtime.evaluate)
- **Server**: Python, FastAPI, WebSockets, pystray (system tray)
- **AI**: Any IDE with file-based communication (OpenCode, Cursor, Windsurf, etc.)
- **Communication**: WebSocket (extension ↔ server), JSON files (server ↔ AI brain)

## License

MIT

---

*Built for support engineers who'd rather fix the problem than explain it.*
