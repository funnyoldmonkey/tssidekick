import json
import asyncio
import re
import os
import base64
import time
import hashlib
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from gemma import gemma_client
import logging
import codecs
import sys

# Anchor all paths to server/ directory early
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))

# Setup logging to file
log_file = os.path.join(SERVER_DIR, "server.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ts_sidekick")

app = FastAPI()

# Store sessions: {tab_id: {"history": [], "model": "gemma-4-31b-it"}}
sessions = {}

# File paths and directories (all anchored to SERVER_DIR)
SESSIONS_DIR = os.path.join(SERVER_DIR, "sessions")
BRAIN_INPUT = os.path.join(SERVER_DIR, "brain_input.json")
BRAIN_OUTPUT = os.path.join(SERVER_DIR, "brain_output.json")
BRAIN_READY_FLAG = os.path.join(SERVER_DIR, "brain_ready.flag")
brain_turn_counter = 0
SCRATCH_DIR = os.path.join(SERVER_DIR, "..", "scratch")
SCRATCH_NET_BODIES = os.path.join(SCRATCH_DIR, "obs_net_bodies")
KB_DIR = os.path.join(SERVER_DIR, "..", "kb")
KB_FIXES_LOG = os.path.join(KB_DIR, "fixes.log")
PLAYBOOKS_PATH = os.path.join(SERVER_DIR, "..", "playbooks", "PLAYBOOKS.md")

# Local search actions that don't need the extension
LOCAL_ACTIONS = {"search_dom", "search_console", "search_network", "read_network_body", "refresh_files", "diagnose", "log_fix", "search_playbook"}

# Max history turns to keep (prevents free-tier context overflow)
MAX_HISTORY_TURNS = 20

# Path to the brain protocol doc (injected into brain_input.json every turn)
BRAIN_PROTOCOL_PATH = os.path.join(SERVER_DIR, "..", "TS_SIDEKICK_BRAIN.md")

for d in [SESSIONS_DIR, SCRATCH_DIR, SCRATCH_NET_BODIES, KB_DIR]:
    os.makedirs(d, exist_ok=True)


def read_json_file(filepath):
    """Read a JSON file with automatic encoding detection.
    Handles UTF-8, UTF-8 with BOM, UTF-16 LE/BE, and other encodings
    that IDEs may use when writing brain_output.json."""
    with open(filepath, "rb") as f:
        raw = f.read()

    # Detect and strip BOM, determine encoding
    for bom, encoding in [
        (codecs.BOM_UTF32_LE, "utf-32-le"),
        (codecs.BOM_UTF32_BE, "utf-32-be"),
        (codecs.BOM_UTF16_LE, "utf-16-le"),
        (codecs.BOM_UTF16_BE, "utf-16-be"),
        (codecs.BOM_UTF8, "utf-8-sig"),
    ]:
        if raw.startswith(bom):
            text = raw.decode(encoding)
            # utf-8-sig auto-strips BOM; for others, strip manually
            if encoding != "utf-8-sig":
                text = raw[len(bom):].decode(encoding)
            return json.loads(text)

    # No BOM — try UTF-8 (most common)
    return json.loads(raw.decode("utf-8"))

SYSTEM_PROMPT = """You are TS Sidekick V2, an elite autonomous Tier 2 support agent.
You operate in a continuous loop. Your goal is to diagnose issues, fix them, VERIFY the fix, and only THEN report to the user.

## GOLDEN RULE: SILENT UNTIL SOLVED
Do NOT use post_message until you have either:
- A verified working fix (confirmed via screenshot + DOM check), OR
- Exhausted 3+ fix attempts and need user input.
Work silently. The user doesn't need play-by-play updates.

## UNIVERSAL DIAGNOSTIC FRAMEWORK
Every investigation follows these steps regardless of scenario:
1. **`diagnose`** — Always start here. The server cross-references scripts, DOM, console, network and auto-detects the scenario type.
2. **Read the diagnosis packet** — Check `detected_scenario` to know which playbook to follow. Review `potential_issues` for auto-flagged problems.
3. **Deep investigation** — Use search tools (`search_dom`, `search_console`, `search_network`, `read_network_body`) to drill into specific evidence. These are instant and don't cost extension roundtrips.
4. **Hypothesize** — State your root cause theory in your `thought`.
5. **Fix** — Apply via `inject_js`, `inject_css`, `click`, `type`, etc.
6. **Verify** — Check screenshot + DOM/console after re-observation. If not fixed, try a different approach.
7. **Report** — Only after verified fix or 3+ failed attempts.

## FIX-AND-VERIFY LOOP
1. Inject fix via `inject_js` or `inject_css`.
2. After re-observation: check screenshot, `search_dom`, `inspect_element`.
3. If NOT fixed: review `previous_fix_attempts`, try a DIFFERENT approach.
4. Escalation order: CSS fix → JS re-init → DOM reconstruction → user notification.
5. After 3 failed attempts, `post_message` with: root cause, what you tried, what the user needs to do.

## SCENARIO PLAYBOOKS
The `diagnose` action auto-detects the scenario. Follow the matching playbook:

### PLAYBOOK: WIDGET_NOT_SHOWING
An injected widget, button, or UI element is not rendering.
1. Find the app's script in the diagnosis (check `scripts` + `network_status`).
2. `read_network_body` to see what selectors/elements the script creates.
3. `search_dom` for the target container the script expects.
4. Check `hidden_elements` — the widget may exist but be hidden by CSS.
5. `search_console` for errors from the script's domain.
6. Common fixes: CSS `display` override, re-initialize widget JS, create missing container.

### PLAYBOOK: SHOPIFY_APP
A Shopify app's functionality is broken or not rendering.
- Shopify themes use Liquid templates (server-side). App blocks must be added via Theme Customizer → App embeds.
- Apps inject via ScriptTag API (`<head>`) or App Blocks (theme sections).
- Script CDN patterns: `cdn.shopify.com/extensions/`, app-specific domains.
- Theme CSS specificity often overrides app CSS — check for `!important` conflicts.
- Shopify CSP headers exist — `inject_js` via debugger bypasses them.
- Key selectors: `form[action*="/cart/add"]`, `product-form`, `.product-form__submit`, `button[name="add"]`, `[data-add-to-cart]`.
- If app block container missing → user must add via Theme Customizer (can't fix with JS).

### PLAYBOOK: FORM_SUBMISSION
A form is not submitting, validating incorrectly, or losing data.
1. `search_dom("form")` to find all forms and their `action`/`method` attributes.
2. `search_dom("input")` to check for required fields, hidden inputs, CSRF tokens.
3. `search_console("submit")` or `search_console("validation")` for JS errors on submit.
4. `search_network("/api")` or the form's action URL to see if the request was made.
5. Check for: missing CSRF token, disabled submit button, `preventDefault` in JS, form action mismatch.
6. Common fixes: remove disabled attribute, dispatch submit event, fill hidden fields, fix validation JS.

### PLAYBOOK: API_NETWORK_ERROR
An API call is failing, returning wrong data, or not being made.
1. Check `failed_requests` in diagnosis for 4xx/5xx responses.
2. `search_network` for the specific API endpoint.
3. `read_network_body` to see the actual response (error messages, malformed data).
4. `search_console` for fetch/XHR errors, CORS errors, timeout messages.
5. Check for: wrong endpoint URL, missing auth headers, CORS policy, rate limiting, malformed request body.
6. Common fixes: retry with correct params via `inject_js`, fix request headers, handle CORS preflight.

### PLAYBOOK: CSS_LAYOUT
Elements are misaligned, overlapping, cut off, or visually broken.
1. `inspect_element` on the broken element — check computed styles (display, position, overflow, z-index).
2. `search_dom("[HIDDEN:")` for elements hidden by CSS.
3. `capture_element` for a high-res crop of the problem area.
4. Look for: overflow:hidden on parent, z-index stacking, flexbox/grid miscalculation, media query not matching, CSS specificity override.
5. Common fixes: `inject_css` with targeted overrides using `!important`, fix z-index stacking, adjust overflow.

### PLAYBOOK: AUTH_SESSION
Login failures, session expiration, redirect loops, or permission errors.
1. `search_network("login")` or `search_network("auth")` for auth-related requests.
2. `search_network("401")` or `search_network("403")` for permission failures.
3. `search_console("token")` or `search_console("session")` for auth errors.
4. Check cookies via `search_network("cookie")`.
5. Look for: expired token, missing cookie, CSRF mismatch, OAuth redirect loop, SSO configuration error.
6. Common fixes: `clear_site_data` and retry, inject fresh token via JS, fix redirect URL.

### PLAYBOOK: THIRD_PARTY_EMBED
A third-party integration (chat widget, analytics, payment form, social embed) is broken.
1. Find the third-party script in diagnosis `scripts` list.
2. Check its `network_status` — did it load?
3. `search_console` for the third-party's domain to find errors.
4. Check for: CSP blocking, ad blocker interference, script load order, missing container div, iframe sandbox restrictions.
5. Common fixes: inject the script again via `inject_js`, create missing container, adjust CSP via meta tag.

### PLAYBOOK: CART_CHECKOUT
Cart not updating, discount codes failing, quantity issues, or checkout redirect problems.
1. `search_dom` for cart forms and hidden inputs (variant ID, quantity).
2. `search_network("/cart/add|/cart/update|/cart/change|/discount")` for cart API calls and responses.
3. `read_network_body` on cart/discount endpoints for error details.
4. `search_console("cart|discount|variant|inventory")` for related JS errors.
5. Check for: wrong variant ID, out-of-stock, discount expired/minimum not met, app scripts intercepting cart, redirect not sticking.
6. Common fixes: re-enable submit button, correct variant ID, re-apply discount via fetch, remove interfering script, dispatch cart update event.

### PLAYBOOK: PERFORMANCE_RENDER
Page loads but elements are slow, flickering, or showing flash of unstyled content.
1. `search_dom("script")` for render-blocking scripts without `defer`/`async`.
2. `search_console("layout shift|CLS|paint|render|slow")` for performance warnings.
3. `search_network` for slow/large responses.
4. `inspect_element` on shifting elements for late-applied styles.
5. Check for: blocking scripts in head, app blocks causing layout shift, images without dimensions, CSS loaded via JS, font FOIT/FOUT.
6. Common fixes: add `defer`/`async` via `inject_js`, set dimensions via `inject_css`, preload critical resources, `font-display: swap`.

### PLAYBOOK: GENERAL
No specific scenario detected — use general debugging approach.
1. Review ALL sections of the diagnosis packet.
2. Prioritize: console errors first, then network failures, then hidden elements.
3. `search_console("error")` for any JS exceptions.
4. `search_network("FAILED")` for broken requests.
5. Cross-reference errors with scripts to identify the culprit.
6. Apply targeted fix, verify, iterate.

## OUTPUT FORMAT
{
  "thought": "Detailed reasoning. Include: scenario detected, evidence found, hypothesis, fix plan, verification method.",
  "action": "click" | "type" | "inject_js" | "inject_css" | "navigate" | "scroll" | "hover" | "post_message" | "observe" | "run_test" | "inspect_element" | "get_network_body" | "clear_site_data" | "capture_element" | "click_at_position" | "search_dom" | "search_console" | "search_network" | "read_network_body" | "refresh_files" | "diagnose" | "search_playbook" | "log_fix",
  "payload": { ... }
}
"""


# ── Scratch File Helpers ─────────────────────────────────────────────────────

def write_scratch_files(obs):
    """Write full observation data to scratch files. No truncation."""
    try:
        # DOM
        dom_path = os.path.join(SCRATCH_DIR, "obs_dom.txt")
        with open(dom_path, "w", encoding="utf-8") as f:
            f.write(obs.get("dom", ""))

        # Console logs
        console_path = os.path.join(SCRATCH_DIR, "obs_console.log")
        with open(console_path, "w", encoding="utf-8") as f:
            f.write(obs.get("console", ""))

        # Network log
        network_path = os.path.join(SCRATCH_DIR, "obs_network.log")
        with open(network_path, "w", encoding="utf-8") as f:
            f.write(obs.get("network", ""))

        # Extract and save individual network bodies to separate files
        network_raw = obs.get("network", "")
        for line in network_raw.split('\n'):
            if line.startswith('📦 DATA ['):
                try:
                    # Format: 📦 DATA [cleanUrl]: body
                    bracket_end = line.index(']')
                    url_key = line[len('📦 DATA ['):bracket_end]
                    body = line[bracket_end + 2:]  # skip ]:
                    url_hash = hashlib.md5(url_key.encode()).hexdigest()[:12]
                    body_path = os.path.join(SCRATCH_NET_BODIES, f"{url_key}_{url_hash}.txt")
                    # Sanitize filename
                    safe_name = re.sub(r'[<>:"/\\|?*]', '_', url_key)
                    body_path = os.path.join(SCRATCH_NET_BODIES, f"{safe_name}_{url_hash}.txt")
                    with open(body_path, "w", encoding="utf-8") as f:
                        f.write(body)
                except Exception:
                    pass

        logger.info(f"Scratch files written to {SCRATCH_DIR}")
    except Exception as e:
        logger.error(f"Failed to write scratch files: {e}")


def build_slim_observation(obs):
    """Build a context-friendly slim observation for brain_input.json."""
    dom_raw = obs.get("dom", "")
    console_raw = obs.get("console", "")
    network_raw = obs.get("network", "")

    # DOM summary: counts + first/last few interactive elements
    dom_lines = dom_raw.split('\n') if dom_raw else []
    interactive_lines = [l for l in dom_lines if l.startswith('★')]
    all_lines = [l for l in dom_lines if l.startswith('·') or l.startswith('★')]

    dom_summary = {
        "total_elements": len(all_lines),
        "interactive_elements": len(interactive_lines),
        "hint": "Use search_dom(query) to find specific elements in scratch/obs_dom.txt",
        "preview": interactive_lines[:30]  # First 30 interactive elements as preview
    }

    # Console summary: last 20 lines + error count
    console_lines = console_raw.split('\n') if console_raw else []
    error_count = sum(1 for l in console_lines if '[error]' in l.lower() or '🚨' in l)

    console_summary = {
        "total_lines": len(console_lines),
        "error_count": error_count,
        "hint": "Use search_console(query) to find specific logs in scratch/obs_console.log",
        "recent": console_lines[-20:] if console_lines else []
    }

    # Network summary: last 20 entries + failure count
    network_lines = network_raw.split('\n') if network_raw else []
    fail_count = sum(1 for l in network_lines if '🚨 FAILED' in l)

    network_summary = {
        "total_requests": len(network_lines),
        "failed_requests": fail_count,
        "hint": "Use search_network(query) to find specific requests in scratch/obs_network.log. Use read_network_body(filename) to read full response bodies from scratch/obs_net_bodies/",
        "recent": network_lines[-20:] if network_lines else []
    }

    return {
        "dom": dom_summary,
        "console": console_summary,
        "network": network_summary,
        "url": obs.get("url", "")
    }


def handle_local_search(action_name, payload):
    """Handle search actions locally without roundtripping to the extension."""
    query = payload.get("query", "")

    if action_name == "search_dom":
        return _grep_file(os.path.join(SCRATCH_DIR, "obs_dom.txt"), query)

    elif action_name == "search_console":
        return _grep_file(os.path.join(SCRATCH_DIR, "obs_console.log"), query)

    elif action_name == "search_network":
        return _grep_file(os.path.join(SCRATCH_DIR, "obs_network.log"), query)

    elif action_name == "read_network_body":
        filename = payload.get("filename", "")
        # Search for a matching file in obs_net_bodies
        if filename:
            for f in os.listdir(SCRATCH_NET_BODIES):
                if filename.lower() in f.lower():
                    filepath = os.path.join(SCRATCH_NET_BODIES, f)
                    with open(filepath, "r", encoding="utf-8") as fh:
                        return {"file": f, "body": fh.read()}
        # If no filename, list available bodies
        available = os.listdir(SCRATCH_NET_BODIES) if os.path.exists(SCRATCH_NET_BODIES) else []
        return {"available_files": available, "hint": "Provide a filename or partial match in payload.filename"}

    elif action_name == "diagnose":
        return cross_reference_diagnostics()

    elif action_name == "log_fix":
        # Accept entry from multiple possible payload fields (brain may use different keys)
        entry = payload.get("entry", "") or payload.get("message", "") or payload.get("text", "") or payload.get("content", "") or payload.get("query", "")
        if not entry:
            logger.warning(f"⚠️ log_fix called but no entry found. Payload keys: {list(payload.keys())}")
            return {"error": f"No entry provided. Payload must include 'entry' with the formatted fix log text. Received keys: {list(payload.keys())}"}
        logger.info(f"📝 log_fix received entry ({len(entry)} chars)")
        return append_fix_to_kb(entry)

    elif action_name == "search_playbook":
        return _search_playbook(query)

    return {"error": f"Unknown local action: {action_name}"}


def _search_playbook(query):
    """Search PLAYBOOKS.md by section. Returns full sections whose header or tags match the query.
    This gives the AI complete recipes, not just matching lines."""
    if not os.path.exists(PLAYBOOKS_PATH):
        return {"error": "PLAYBOOKS.md not found", "sections": []}

    try:
        with open(PLAYBOOKS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return {"error": str(e), "sections": []}

    # Split into sections by ## headers
    sections = []
    current_header = None
    current_lines = []
    current_tags = ""

    for line in content.split("\n"):
        if line.startswith("## "):
            # Save previous section
            if current_header:
                sections.append({
                    "header": current_header,
                    "tags": current_tags,
                    "content": "\n".join(current_lines)
                })
            current_header = line.strip()
            current_lines = [line]
            current_tags = ""
        else:
            current_lines.append(line)
            if line.strip().startswith("[TAGS:"):
                current_tags = line.strip()

    # Don't forget last section
    if current_header:
        sections.append({
            "header": current_header,
            "tags": current_tags,
            "content": "\n".join(current_lines)
        })

    # Search sections — match against header, tags, and content
    try:
        pattern = re.compile(query, re.IGNORECASE)
        use_regex = True
    except re.error:
        use_regex = False

    matches = []
    for sec in sections:
        searchable = f"{sec['header']} {sec['tags']} {sec['content']}"
        hit = False
        if use_regex:
            hit = bool(pattern.search(searchable))
        else:
            hit = query.lower() in searchable.lower()

        if hit:
            # Cap each section at 3000 chars to avoid blowing up brain_input
            trimmed = sec["content"][:3000]
            if len(sec["content"]) > 3000:
                trimmed += "\n... [section truncated — use more specific query]"
            matches.append({
                "header": sec["header"],
                "tags": sec["tags"],
                "content": trimmed
            })

    # Cap total sections returned
    return {
        "query": query,
        "file": "PLAYBOOKS.md",
        "total_sections_matched": len(matches),
        "sections": matches[:3],  # Max 3 sections per search — search again with different keywords for more
        "truncated": len(matches) > 3,
        "hint": "Use more specific queries (e.g., 'add to cart|button|broken') to narrow results." if len(matches) > 3 else ""
    }


def _grep_file(filepath, query):
    """Search a file for lines matching a query (case-insensitive).
    Supports pipe-separated OR queries (e.g., 'preorder|location|inventory')
    and falls back to regex if the query contains regex metacharacters."""
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}", "matches": []}

    matches = []
    try:
        # Support pipe-separated OR queries and regex patterns
        try:
            pattern = re.compile(query, re.IGNORECASE)
            use_regex = True
        except re.error:
            use_regex = False

        with open(filepath, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if use_regex:
                    if pattern.search(line):
                        matches.append({"line": i, "content": line.rstrip()})
                else:
                    if query.lower() in line.lower():
                        matches.append({"line": i, "content": line.rstrip()})
    except Exception as e:
        return {"error": str(e), "matches": []}

    return {
        "query": query,
        "file": os.path.basename(filepath),
        "total_matches": len(matches),
        "matches": matches[:100],  # Cap results at 100 to keep brain_input reasonable
        "truncated": len(matches) > 100
    }


# ── Cross-Reference Diagnostic Engine ────────────────────────────────────────

def cross_reference_diagnostics():
    """Pre-correlate scripts, DOM targets, console errors, and hidden elements
    into a structured diagnosis packet. Auto-detects scenario type.
    Runs entirely server-side."""

    diagnosis = {
        "scripts": [],
        "hidden_elements": [],
        "console_errors": [],
        "failed_requests": [],
        "potential_issues": [],
        "forms": [],
        "auth_signals": [],
        "third_party_embeds": []
    }

    dom_path = os.path.join(SCRATCH_DIR, "obs_dom.txt")
    console_path = os.path.join(SCRATCH_DIR, "obs_console.log")
    network_path = os.path.join(SCRATCH_DIR, "obs_network.log")

    dom_raw = ""
    dom_lines = []
    console_raw = ""
    network_raw = ""

    # ── 1. Load all scratch files ────────────────────────────────────────
    if os.path.exists(dom_path):
        with open(dom_path, "r", encoding="utf-8") as f:
            dom_raw = f.read()
            dom_lines = dom_raw.split('\n')

    if os.path.exists(console_path):
        with open(console_path, "r", encoding="utf-8") as f:
            console_raw = f.read()

    if os.path.exists(network_path):
        with open(network_path, "r", encoding="utf-8") as f:
            network_raw = f.read()

    # ── 2. Analyze scripts from DOM ──────────────────────────────────────
    for i, line in enumerate(dom_lines, 1):
        line = line.rstrip()
        if line.startswith('📜 [script] src="'):
            src = line.split('src="')[1].rstrip('"')
            diagnosis["scripts"].append({"line": i, "src": src, "type": "external"})
        elif line.startswith('📜 [script:inline]'):
            snippet = line.split('"')[1] if '"' in line else ""
            diagnosis["scripts"].append({"line": i, "snippet": snippet[:150], "type": "inline"})

        # Hidden elements
        if '[HIDDEN:' in line:
            diagnosis["hidden_elements"].append({"line": i, "element": line})

    # ── 3. Analyze forms ─────────────────────────────────────────────────
    for i, line in enumerate(dom_lines, 1):
        line_lower = line.lower()
        if '★ [form' in line_lower or '· [form' in line_lower:
            diagnosis["forms"].append({"line": i, "element": line.rstrip()})
        # Collect input/select/textarea inside forms for context
        if any(tag in line_lower for tag in ['★ [input', '★ [select', '★ [textarea', '★ [button']):
            if 'disabled' in line_lower or '[HIDDEN:' in line:
                diagnosis["potential_issues"].append(f"Interactive element may be disabled or hidden (line {i}): {line.rstrip()[:120]}")

    # ── 4. Analyze console errors ────────────────────────────────────────
    error_keywords = ['[error]', 'uncaught', 'failed', 'refused', 'blocked',
                      'exception', 'typeerror', 'referenceerror', 'syntaxerror',
                      'cors', 'csp', 'content security policy', '403', '401', '404']
    for i, line in enumerate(console_raw.split('\n'), 1):
        line = line.rstrip()
        if any(kw in line.lower() for kw in error_keywords):
            diagnosis["console_errors"].append({"line": i, "message": line})

    # ── 5. Analyze network failures ──────────────────────────────────────
    for i, line in enumerate(network_raw.split('\n'), 1):
        line = line.rstrip()
        if '🚨 FAILED' in line:
            diagnosis["failed_requests"].append({"line": i, "request": line})

    # ── 6. Cross-reference: script src vs network status ─────────────────
    from urllib.parse import urlparse

    for script in diagnosis["scripts"]:
        if script["type"] == "external":
            src = script["src"]
            src_short = src.split('?')[0].split('/')[-1]
            if any(src_short in req["request"] for req in diagnosis["failed_requests"]):
                script["network_status"] = "FAILED"
                diagnosis["potential_issues"].append(f"Script '{src_short}' is in the DOM but its network request FAILED")
            elif src_short in network_raw:
                script["network_status"] = "LOADED"
            else:
                script["network_status"] = "NOT_SEEN_IN_NETWORK"

    # ── 7. Cross-reference: scripts vs console errors ────────────────────
    for script in diagnosis["scripts"]:
        if script["type"] == "external":
            try:
                src_domain = urlparse(script["src"]).netloc
            except Exception:
                src_domain = ""
            if src_domain:
                related_errors = [e for e in diagnosis["console_errors"] if src_domain in e["message"]]
                if related_errors:
                    script["related_errors"] = related_errors[:5]
                    diagnosis["potential_issues"].append(f"Script from '{src_domain}' has {len(related_errors)} console error(s)")

    # ── 8. Detect auth/session signals ───────────────────────────────────
    auth_keywords_console = ['token', 'session', 'unauthorized', '401', '403', 'login', 'oauth', 'csrf', 'forbidden']
    auth_keywords_network = ['401', '403', 'login', 'auth', 'oauth', 'token', 'session', 'signin']

    for err in diagnosis["console_errors"]:
        if any(kw in err["message"].lower() for kw in auth_keywords_console):
            diagnosis["auth_signals"].append({"source": "console", "detail": err})

    for req in diagnosis["failed_requests"]:
        if any(kw in req["request"].lower() for kw in auth_keywords_network):
            diagnosis["auth_signals"].append({"source": "network", "detail": req})

    # ── 9. Detect third-party embeds ─────────────────────────────────────
    known_third_party = ['intercom', 'drift', 'zendesk', 'tawk', 'crisp', 'hotjar',
                         'google-analytics', 'gtag', 'gtm', 'facebook', 'fb-', 'twitter',
                         'stripe', 'paypal', 'braintree', 'recaptcha', 'hcaptcha',
                         'youtube', 'vimeo', 'instagram', 'tiktok', 'pinterest',
                         'klaviyo', 'mailchimp', 'hubspot', 'segment', 'mixpanel']

    for script in diagnosis["scripts"]:
        if script["type"] == "external":
            src_lower = script["src"].lower()
            for tp in known_third_party:
                if tp in src_lower:
                    embed_info = {"service": tp, "src": script["src"], "network_status": script.get("network_status", "UNKNOWN")}
                    if script.get("related_errors"):
                        embed_info["has_errors"] = True
                    diagnosis["third_party_embeds"].append(embed_info)
                    break

    # ── 10. Platform detection ───────────────────────────────────────────
    platform_markers = {
        "shopify": any(kw in dom_raw.lower() for kw in ['shopify', 'myshopify', '/cart/add', 'product-form']),
        "wordpress": any(kw in dom_raw.lower() for kw in ['wp-content', 'wp-includes', 'wordpress']),
        "wix": 'wix' in dom_raw.lower() or 'parastorage' in dom_raw.lower(),
        "squarespace": 'squarespace' in dom_raw.lower(),
        "webflow": 'webflow' in dom_raw.lower(),
        "magento": any(kw in dom_raw.lower() for kw in ['magento', 'mage-init']),
        "bigcommerce": 'bigcommerce' in dom_raw.lower()
    }
    detected_platform = next((p for p, v in platform_markers.items() if v), "unknown")
    diagnosis["platform"] = detected_platform

    # Shopify-specific context
    if detected_platform == "shopify":
        diagnosis["shopify_context"] = {
            "app_blocks": 'data-app-block' in dom_raw or 'shopify-block' in dom_raw,
            "product_form": 'action="/cart/add"' in dom_raw or 'product-form' in dom_raw,
            "cart_form": '/cart' in dom_raw,
            "bis_container": any(kw in dom_raw for kw in ['bis-container', 'bis_', 'BIS_']),
            "add_to_cart_button": any(kw in dom_raw for kw in ['add-to-cart', 'AddToCart', 'product-form__submit'])
        }

    # ── 11. Auto-detect scenario type ────────────────────────────────────
    scenario_scores = {
        "WIDGET_NOT_SHOWING": 0,
        "SHOPIFY_APP": 0,
        "FORM_SUBMISSION": 0,
        "API_NETWORK_ERROR": 0,
        "CSS_LAYOUT": 0,
        "AUTH_SESSION": 0,
        "THIRD_PARTY_EMBED": 0,
        "CART_CHECKOUT": 0,
        "PERFORMANCE_RENDER": 0,
        "GENERAL": 0
    }

    # Score based on signals
    if diagnosis["hidden_elements"]:
        scenario_scores["WIDGET_NOT_SHOWING"] += 3
        scenario_scores["CSS_LAYOUT"] += 2

    if any(s.get("network_status") == "FAILED" for s in diagnosis["scripts"]):
        scenario_scores["WIDGET_NOT_SHOWING"] += 3

    # CSS/Layout signals — console errors about styling, positioning, visibility
    css_keywords = ['css', 'layout', 'overflow', 'z-index', 'position', 'visibility', 'opacity', 'hidden', 'misaligned', 'off-screen', 'clipped', 'collapsed']
    css_console_hits = sum(1 for e in diagnosis["console_errors"] if any(kw in e["message"].lower() for kw in css_keywords))
    if css_console_hits:
        scenario_scores["CSS_LAYOUT"] += min(css_console_hits * 2, 8)  # stacks up to +8
    # Multiple hidden elements is a strong CSS/layout signal
    if len(diagnosis["hidden_elements"]) > 3:
        scenario_scores["CSS_LAYOUT"] += 2
    if len(diagnosis["hidden_elements"]) > 8:
        scenario_scores["CSS_LAYOUT"] += 2

    # SHOPIFY_APP — only scores on actual app-interference signals, NOT platform alone
    if detected_platform == "shopify":
        # App-block / app-embed elements in DOM = strong app interference signal
        app_dom_keywords = ['app-block', 'app-embed', 'shopify-app', 'data-app-id', 'data-app-block']
        app_dom_hits = sum(1 for kw in app_dom_keywords if kw in dom_raw.lower())
        if app_dom_hits:
            scenario_scores["SHOPIFY_APP"] += 2 + app_dom_hits  # +3 to +7 depending on matches
        # App proxy route failures (e.g. /apps/*, /tools/*)
        app_proxy_failures = [r for r in diagnosis["failed_requests"] if '/apps/' in r["request"].lower() or '/tools/' in r["request"].lower()]
        if app_proxy_failures:
            scenario_scores["SHOPIFY_APP"] += 3
        # Console errors mentioning app names or app-specific patterns
        app_console_keywords = ['app-block', 'app-embed', 'shopify-section', 'theme-app-extension', 'app proxy']
        if any(any(kw in e["message"].lower() for kw in app_console_keywords) for e in diagnosis["console_errors"]):
            scenario_scores["SHOPIFY_APP"] += 3

    if diagnosis["forms"]:
        scenario_scores["FORM_SUBMISSION"] += 2
    # Form-specific console errors (validation, submission failures)
    form_keywords = ['form', 'submit', 'validation', 'required', 'invalid', 'input', 'field', 'captcha', 'recaptcha']
    form_console_hits = sum(1 for e in diagnosis["console_errors"] if any(kw in e["message"].lower() for kw in form_keywords))
    if form_console_hits:
        scenario_scores["FORM_SUBMISSION"] += min(form_console_hits * 2, 6)
    # Forms with hidden or broken submit buttons
    if diagnosis["forms"] and any('submit' in el.get("element", "").lower() or 'form' in el.get("element", "").lower() for el in diagnosis["hidden_elements"]):
        scenario_scores["FORM_SUBMISSION"] += 3

    if len(diagnosis["failed_requests"]) > 2:
        scenario_scores["API_NETWORK_ERROR"] += 3

    if any('cors' in e["message"].lower() for e in diagnosis["console_errors"]):
        scenario_scores["API_NETWORK_ERROR"] += 2

    if diagnosis["auth_signals"]:
        scenario_scores["AUTH_SESSION"] += len(diagnosis["auth_signals"])

    if diagnosis["third_party_embeds"]:
        scenario_scores["THIRD_PARTY_EMBED"] += 2
        broken_embeds = [e for e in diagnosis["third_party_embeds"] if e.get("has_errors") or e.get("network_status") == "FAILED"]
        if broken_embeds:
            scenario_scores["THIRD_PARTY_EMBED"] += 3

    # Cart/checkout signals
    cart_keywords_network = ['/cart/add', '/cart/update', '/cart/change', '/discount', '/checkout']
    cart_failures = [r for r in diagnosis["failed_requests"] if any(kw in r["request"].lower() for kw in cart_keywords_network)]
    if cart_failures:
        scenario_scores["CART_CHECKOUT"] += 4
    cart_keywords_console = ['cart', 'discount', 'variant', 'inventory', 'quantity', 'checkout']
    cart_console_hits = sum(1 for e in diagnosis["console_errors"] if any(kw in e["message"].lower() for kw in cart_keywords_console))
    if cart_console_hits:
        scenario_scores["CART_CHECKOUT"] += min(cart_console_hits * 2, 6)  # stacks up to +6
    # Shopify cart form/drawer present
    if detected_platform == "shopify" and any(kw in dom_raw.lower() for kw in ['action="/cart/add"', '/cart/update', 'cart-drawer', 'cart-notification']):
        scenario_scores["CART_CHECKOUT"] += 2
    # Cart DOM sabotage signals — disabled submit buttons, sold out states, fake banners
    cart_dom_signals = 0
    if any('add to cart' in el.get("element", "").lower() or 'cart' in el.get("element", "").lower() for el in diagnosis["hidden_elements"]):
        cart_dom_signals += 3
    # Disabled submit button inside a cart form
    if 'product-form__submit' in dom_raw.lower() and ('disabled' in dom_raw.lower()):
        if any(kw in dom_raw.lower() for kw in ['sold out', 'sold-out', 'out of stock', 'out-of-stock', 'unavailable']):
            cart_dom_signals += 3
    # Fake stock/inventory banners injected into DOM
    if any(kw in dom_raw.lower() for kw in ['fake-stock', 'out of stock', 'stock-banner', 'inventory-warning']):
        cart_dom_signals += 2
    scenario_scores["CART_CHECKOUT"] += cart_dom_signals

    # Performance/render signals
    perf_keywords = ['layout shift', 'cls', 'cumulative layout', 'render-blocking', 'long task', 'slow', 'paint', 'font', 'fouc', 'foit']
    perf_console_hits = sum(1 for e in diagnosis["console_errors"] if any(kw in e["message"].lower() for kw in perf_keywords))
    if perf_console_hits:
        scenario_scores["PERFORMANCE_RENDER"] += min(perf_console_hits * 2, 8)  # stacks up to +8
    # Many scripts = potential render blocking
    blocking_scripts = [s for s in diagnosis["scripts"] if s["type"] == "external"]
    if len(blocking_scripts) > 15:
        scenario_scores["PERFORMANCE_RENDER"] += 3
    elif len(blocking_scripts) > 10:
        scenario_scores["PERFORMANCE_RENDER"] += 1
    # Late-injected styles in DOM (FOUC signal)
    if any(kw in dom_raw.lower() for kw in ['late-style', 'injected-style', 'fouc-']):
        scenario_scores["PERFORMANCE_RENDER"] += 2

    if diagnosis["console_errors"]:
        scenario_scores["GENERAL"] += 1

    # Detect scenario — pick highest score, fallback to GENERAL
    # Tiebreaker: specific issue-type scenarios beat generic platform scenarios
    tiebreaker_priority = [
        "CART_CHECKOUT", "PERFORMANCE_RENDER", "API_NETWORK_ERROR",
        "AUTH_SESSION", "CSS_LAYOUT", "FORM_SUBMISSION", "WIDGET_NOT_SHOWING",
        "THIRD_PARTY_EMBED", "SHOPIFY_APP", "GENERAL"
    ]
    max_score = max(scenario_scores.values())
    if max_score == 0:
        detected_scenario = "GENERAL"
    else:
        # Among all scenarios tied at max_score, pick the one with highest tiebreaker priority
        tied = [s for s, c in scenario_scores.items() if c == max_score]
        detected_scenario = min(tied, key=lambda s: tiebreaker_priority.index(s) if s in tiebreaker_priority else 99)

    # Log scenario scores for debugging
    scores_str = ", ".join(f"{s}={c}" for s, c in sorted(scenario_scores.items(), key=lambda x: x[1], reverse=True) if c > 0)
    logger.info(f"📊 Scenario scores: {scores_str or 'all zero'} → {detected_scenario}")

    # Build ranked list of likely scenarios
    ranked = sorted(scenario_scores.items(), key=lambda x: x[1], reverse=True)
    ranked = [{"scenario": s, "confidence": c} for s, c in ranked if c > 0]

    diagnosis["detected_scenario"] = detected_scenario
    diagnosis["scenario_ranking"] = ranked[:3]

    # ── 12. Hidden elements summary ──────────────────────────────────────
    if diagnosis["hidden_elements"]:
        diagnosis["potential_issues"].append(f"Found {len(diagnosis['hidden_elements'])} hidden elements — check if any are the target widget/component")

    # ── 13. Available network bodies ─────────────────────────────────────
    if os.path.exists(SCRATCH_NET_BODIES):
        diagnosis["available_network_bodies"] = os.listdir(SCRATCH_NET_BODIES)
    else:
        diagnosis["available_network_bodies"] = []

    # ── Summary ──────────────────────────────────────────────────────────
    diagnosis["summary"] = {
        "detected_scenario": detected_scenario,
        "platform": detected_platform,
        "total_scripts": len(diagnosis["scripts"]),
        "external_scripts": sum(1 for s in diagnosis["scripts"] if s["type"] == "external"),
        "hidden_elements_count": len(diagnosis["hidden_elements"]),
        "console_errors_count": len(diagnosis["console_errors"]),
        "failed_network_requests": len(diagnosis["failed_requests"]),
        "forms_count": len(diagnosis["forms"]),
        "auth_signals_count": len(diagnosis["auth_signals"]),
        "third_party_embeds_count": len(diagnosis["third_party_embeds"]),
        "issues_found": len(diagnosis["potential_issues"]),
        "recommended_playbook": detected_scenario
    }

    return diagnosis


# ── Knowledge Base (fixes.log) ─────────────────────────────────────────────

def append_fix_to_kb(entry_text):
    """Append a verified fix entry to kb/fixes.log."""
    try:
        with open(KB_FIXES_LOG, "a", encoding="utf-8") as f:
            f.write(entry_text.strip() + "\n")
        logger.info(f"📝 Fix logged to {KB_FIXES_LOG}")
        return {"success": True, "message": "Fix logged to knowledge base."}
    except Exception as e:
        logger.error(f"Failed to write to fixes.log: {e}")
        return {"success": False, "error": str(e)}


def find_relevant_fixes(scenario, url):
    """Search kb/fixes.log for entries matching the scenario or URL domain.
    Returns the 5 most recent matching entries."""
    if not os.path.exists(KB_FIXES_LOG):
        return []

    try:
        with open(KB_FIXES_LOG, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return []

    if not content.strip():
        return []

    # Split into individual entries (separated by ---)
    entries = []
    current = []
    for line in content.split('\n'):
        if line.strip() == '---':
            if current:
                entries.append('\n'.join(current))
                current = []
        else:
            current.append(line)
    if current:
        entries.append('\n'.join(current))

    # Build search terms
    search_terms = []
    if scenario and scenario != "GENERAL":
        search_terms.append(scenario.lower())

    # Extract domain from URL
    if url:
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace('www.', '')
            if domain:
                search_terms.append(domain.lower())
        except Exception:
            pass

    if not search_terms:
        return []

    # Find matching entries
    matches = []
    for entry in entries:
        entry_lower = entry.lower()
        if any(term in entry_lower for term in search_terms):
            matches.append(entry.strip())

    # Return last 5 (most recent since file is append-only)
    return matches[-5:]


# ── Brain Protocol Injection ────────────────────────────────────────────────

def load_brain_protocol():
    """Read TS_SIDEKICK_BRAIN.md from disk and return it with a framing instruction.
    This is injected into brain_input.json every turn as the _protocol field,
    so the AI always has the full playbook in context. Reads fresh every turn
    so edits to the doc propagate automatically."""
    try:
        with open(BRAIN_PROTOCOL_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        return (
            "⚠️ CRITICAL INSTRUCTIONS — Read every line below before taking any action. "
            "These are your rules, tools, and playbooks. Do not skip, summarize, or assume you remember them.\n\n"
            + content
        )
    except Exception as e:
        logger.error(f"Failed to read brain protocol from {BRAIN_PROTOCOL_PATH}: {e}")
        return "⚠️ CRITICAL: Could not load protocol. Read TS_SIDEKICK_BRAIN.md immediately before taking any action."


# ── Fix Attempt Tracking ─────────────────────────────────────────────────────

def record_fix_attempt(session, action_data):
    """Track what fixes were attempted so the brain doesn't repeat itself."""
    if "fix_attempts" not in session:
        session["fix_attempts"] = []

    attempt = {
        "attempt_number": len(session["fix_attempts"]) + 1,
        "action": action_data.get("action"),
        "thought": action_data.get("thought", "")[:300],
        "timestamp": int(time.time())
    }

    payload = action_data.get("payload", {})
    if action_data.get("action") == "inject_js":
        attempt["code_preview"] = payload.get("code", "")[:200]
    elif action_data.get("action") == "inject_css":
        attempt["css_preview"] = payload.get("css", "")[:200]

    session["fix_attempts"].append(attempt)
    return attempt


def get_fix_summary(session):
    """Build a summary of past fix attempts for the brain to review."""
    attempts = session.get("fix_attempts", [])
    if not attempts:
        return None
    return {
        "total_attempts": len(attempts),
        "attempts": attempts,
        "hint": "Do NOT repeat a previously attempted fix. Try a different approach."
    }


# ── History Trimming ─────────────────────────────────────────────────────────

def trim_history(session):
    """Keep only the last MAX_HISTORY_TURNS exchanges to prevent context overflow."""
    history = session.get("history", [])
    if len(history) > MAX_HISTORY_TURNS * 2:  # Each turn = user + model
        session["history"] = history[-(MAX_HISTORY_TURNS * 2):]
        logger.info(f"History trimmed to {len(session['history'])} entries")


async def keepalive(websocket: WebSocket, interval: int = 30):
    """Send a ping every `interval` seconds to keep the WebSocket alive.
    Prevents Chrome from killing the service worker on idle connections."""
    try:
        while True:
            await asyncio.sleep(interval)
            await websocket.send_text(json.dumps({"type": "ping"}))
            logger.debug("Ping sent to extension.")
    except Exception:
        pass  # Connection closed — task will be cancelled anyway


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_host = websocket.client.host
    logger.info(f"Extension connected from {client_host}")
    ping_task = asyncio.create_task(keepalive(websocket))
    
    try:
        while True:
            raw_data = await websocket.receive_text()
            with open(os.path.join(SERVER_DIR, "heartbeat.txt"), "w") as f: f.write(f"Received message at {asyncio.get_event_loop().time()}")
            message = json.loads(raw_data)
            
            msg_type = message.get("type")
            tab_id = str(message.get("tabId", "unknown"))
            
            logger.info(f"Received {msg_type} for Tab {tab_id}")
            
            if msg_type == "init":
                sessions[tab_id] = {
                    "history": [],
                    "model": message.get("model", "gemma-4-31b-it"),
                    "user_query": message.get("query")
                }
                logger.info(f"Session initialized for tab {tab_id} using {sessions[tab_id]['model']}")
                
                await websocket.send_text(json.dumps({
                    "type": "command",
                    "action": "observe",
                    "tabId": tab_id
                }))

            elif msg_type == "observation":
                session = sessions.get(tab_id)
                if not session:
                    logger.warning(f"No session found for tab {tab_id}")
                    continue

                obs = message.get("data")
                user_query = session.get("user_query")
                model_choice = session["model"]

                action_data = None

                if model_choice == "antigravity":
                    # ANTIGRAVITY BRAIN MODE
                    logger.info(f"Handing over to Antigravity Brain for Tab {tab_id}...")
                    
                    # Handle Screenshot with timestamp
                    screenshot_rel_path = os.path.join(SERVER_DIR, "current_view.png")
                    if "screenshot" in obs and obs["screenshot"]:
                        try:
                            timestamp = int(time.time())
                            header, encoded = obs["screenshot"].split(",", 1)
                            session_path = os.path.join(SESSIONS_DIR, tab_id)
                            if not os.path.exists(session_path):
                                os.makedirs(session_path)

                            filename = f"view_{timestamp}.png"
                            filepath = os.path.join(session_path, filename)
                            with open(filepath, "wb") as f:
                                f.write(base64.b64decode(encoded))

                            # Also update the server/current_view.png for easy IDE access
                            with open(os.path.join(SERVER_DIR, "current_view.png"), "wb") as f:
                                f.write(base64.b64decode(encoded))

                            screenshot_rel_path = os.path.join(SESSIONS_DIR, tab_id, filename)
                            logger.info(f"Screenshot saved to {filepath}")
                        except Exception as e:
                            logger.error(f"Failed to save screenshot: {e}")

                    # Write full data to scratch files (no truncation)
                    write_scratch_files(obs)

                    # Build slim observation for brain_input.json (context-friendly)
                    slim_obs = build_slim_observation(obs)

                    # Trim history to prevent context overflow on free tier
                    trim_history(session)

                    # Ensure no stale output exists
                    if os.path.exists(BRAIN_OUTPUT): os.remove(BRAIN_OUTPUT)

                    # Build brain input with full protocol + fix attempt history
                    brain_payload = {
                        "_protocol": load_brain_protocol(),
                        "tab_id": tab_id,
                        "query": user_query,
                        "observation": slim_obs,
                        "screenshot_path": screenshot_rel_path,
                        "history": session["history"]
                    }

                    # Include fix attempt summary if any attempts have been made
                    fix_summary = get_fix_summary(session)
                    if fix_summary:
                        brain_payload["previous_fix_attempts"] = fix_summary

                    # Include relevant past fixes from knowledge base
                    obs_url = obs.get("url", "")
                    detected_scenario = session.get("detected_scenario", "")
                    relevant = find_relevant_fixes(detected_scenario, obs_url)
                    if relevant:
                        brain_payload["relevant_fixes"] = relevant
                        logger.info(f"📚 KB match found: {len(relevant)} relevant past fix(es) fed to brain_input.json")

                    temp_input = f"{BRAIN_INPUT}.tmp"
                    with open(temp_input, "w", encoding="utf-8") as f:
                        json.dump(brain_payload, f, indent=2)
                    os.replace(temp_input, BRAIN_INPUT)
                    global brain_turn_counter
                    brain_turn_counter += 1
                    with open(BRAIN_READY_FLAG, "w") as f:
                        f.write(str(brain_turn_counter))
                    logger.info(f"Slim observation written to {BRAIN_INPUT}, turn #{brain_turn_counter}, full data in scratch/")

                    logger.info("Waiting for Antigravity Brain response (brain_output.json)...")

                    while not os.path.exists(BRAIN_OUTPUT):
                        await asyncio.sleep(0.5)

                    # Robust read with retries to avoid race conditions
                    retries = 5
                    while retries > 0:
                        try:
                            action_data = read_json_file(BRAIN_OUTPUT)

                            # SCRIPT TUNNEL: Handle code_file if specified
                            if action_data.get("action") == "inject_js" and "payload" in action_data:
                                payload = action_data["payload"]
                                if "code_file" in payload:
                                    script_path = payload["code_file"]
                                    script_filename = os.path.basename(script_path)
                                    script_abs = os.path.join(SERVER_DIR, script_filename)
                                    if os.path.exists(script_abs):
                                        with open(script_abs, "r", encoding="utf-8") as sf:
                                            payload["code"] = sf.read()
                                        logger.info(f"Tunneling script from {script_abs}...")
                                        os.remove(script_abs)
                                    else:
                                        logger.error(f"code_file not found: {script_abs} — inject_js will fail")
                                        if "code" not in payload:
                                            payload["code"] = f"console.error('TS Sidekick: code_file not found: {script_filename}');"

                            os.remove(BRAIN_OUTPUT)
                            break # Success
                        except (json.JSONDecodeError, PermissionError) as e:
                            retries -= 1
                            if retries == 0:
                                logger.error(f"Malformed JSON in brain_output.json after retries: {e}")
                                # Read raw content so we can show the model what it wrote
                                raw_output = ""
                                try:
                                    with open(BRAIN_OUTPUT, "r", encoding="utf-8") as f:
                                        raw_output = f.read()[:500]
                                except Exception:
                                    raw_output = "(could not read raw content)"
                                if os.path.exists(BRAIN_OUTPUT): os.remove(BRAIN_OUTPUT)
                                # Write error feedback to brain_input.json so model can self-correct
                                error_payload = {
                                    "_protocol": load_brain_protocol(),
                                    "tab_id": tab_id,
                                    "query": user_query,
                                    "error": {
                                        "type": "MALFORMED_JSON",
                                        "message": f"Your last brain_output.json was not valid JSON. Parse error: {str(e)}",
                                        "raw_output_preview": raw_output,
                                        "instructions": "You MUST write valid JSON to server/brain_output.json. Check for: unescaped quotes inside strings, missing commas, line breaks in string values (use \\n instead), and unclosed braces. See the Technical Schema and examples in the protocol above. Try your last action again with properly formatted JSON."
                                    },
                                    "screenshot_path": screenshot_rel_path,
                                    "history": session["history"]
                                }
                                temp_input = f"{BRAIN_INPUT}.tmp"
                                with open(temp_input, "w", encoding="utf-8") as f:
                                    json.dump(error_payload, f, indent=2)
                                os.replace(temp_input, BRAIN_INPUT)
                                brain_turn_counter += 1
                                with open(BRAIN_READY_FLAG, "w") as f:
                                    f.write(str(brain_turn_counter))
                                logger.info(f"JSON error feedback written to {BRAIN_INPUT}, turn #{brain_turn_counter}")
                                # Go back to waiting for a corrected response
                                while not os.path.exists(BRAIN_OUTPUT):
                                    await asyncio.sleep(0.5)
                                retries = 5
                                continue
                            else:
                                await asyncio.sleep(0.2)
                        except Exception as e:
                            logger.error(f"Unexpected error reading brain_output.json: {e}")
                            raw_output = ""
                            try:
                                with open(BRAIN_OUTPUT, "r", encoding="utf-8") as f:
                                    raw_output = f.read()[:500]
                            except Exception:
                                raw_output = "(could not read raw content)"
                            if os.path.exists(BRAIN_OUTPUT): os.remove(BRAIN_OUTPUT)
                            error_payload = {
                                "_protocol": load_brain_protocol(),
                                "tab_id": tab_id,
                                "query": user_query,
                                "error": {
                                    "type": "MALFORMED_JSON",
                                    "message": f"Your last brain_output.json caused an error: {str(e)}",
                                    "raw_output_preview": raw_output,
                                    "instructions": "You MUST write valid JSON to server/brain_output.json. Check for: unescaped quotes inside strings, missing commas, line breaks in string values (use \\n instead), and unclosed braces. See the Technical Schema and examples in the protocol above. Try your last action again with properly formatted JSON."
                                },
                                "screenshot_path": screenshot_rel_path,
                                "history": session["history"]
                            }
                            temp_input = f"{BRAIN_INPUT}.tmp"
                            with open(temp_input, "w", encoding="utf-8") as f:
                                json.dump(error_payload, f, indent=2)
                            os.replace(temp_input, BRAIN_INPUT)
                            brain_turn_counter += 1
                            with open(BRAIN_READY_FLAG, "w") as f:
                                f.write(str(brain_turn_counter))
                            logger.info(f"Error feedback written to {BRAIN_INPUT}, turn #{brain_turn_counter}")
                            while not os.path.exists(BRAIN_OUTPUT):
                                await asyncio.sleep(0.5)
                            retries = 5
                            continue

                else:
                    # STANDARD GEMMA MODE
                    logger.info(f"Querying Gemma for Tab {tab_id}...")
                    prompt = f"User Request: {user_query}\n\nCURRENT OBSERVATION:\nURL: {obs.get('url')}\nDOM:\n{obs.get('dom')}\n\nCONSOLE:\n{obs.get('console')}\n\nNETWORK:\n{obs.get('network')}\n"
                    
                    response_text = await gemma_client.query(
                        model_name=session["model"],
                        system_prompt=SYSTEM_PROMPT,
                        user_content=prompt,
                        history=session["history"]
                    )
                    
                    try:
                        json_match = re.search(r'(\{.*\})', response_text, re.DOTALL)
                        if json_match:
                            action_data = json.loads(json_match.group(1).strip())
                        else:
                            action_data = json.loads(response_text.strip())
                        
                        session["history"].append({"role": "user", "parts": [prompt]})
                        session["history"].append({"role": "model", "parts": [response_text]})
                    except Exception as e:
                        logger.error(f"Error parsing Gemma response: {e}")
                        action_data = {"type": "error", "message": "Parse error."}

                if action_data:
                    action_name = action_data.get('action')
                    if action_name == "terminate":
                        logger.info("Terminate action received. Closing connection.")
                        await websocket.close()
                        break

                    # ── LOCAL ACTION LOOP ─────────────────────────────────
                    # Search/read actions are handled server-side without
                    # roundtripping to the extension. Results go straight
                    # back into brain_input.json for the next Brain turn.
                    # Loop handles unlimited consecutive local actions.
                    MAX_LOCAL_CHAINS = 15  # Safety cap to prevent infinite loops
                    local_chain_count = 0

                    while action_name in LOCAL_ACTIONS and local_chain_count < MAX_LOCAL_CHAINS:
                        if action_name == "refresh_files":
                            # This one DOES need the extension — request a fresh observe
                            logger.info("refresh_files requested, triggering re-observe...")
                            await websocket.send_text(json.dumps({
                                "type": "command",
                                "action": "observe",
                                "tabId": tab_id
                            }))
                            break  # Exit loop — extension will send a new observation
                        else:
                            local_chain_count += 1
                            logger.info(f"Handling local action ({local_chain_count}): {action_name}")
                            search_results = handle_local_search(action_name, action_data.get("payload", {}))

                            # Stash detected scenario from diagnose results
                            if action_name == "diagnose" and isinstance(search_results, dict):
                                session["detected_scenario"] = search_results.get("detected_scenario", "")

                            # Write results directly to brain_input.json — no extension involved
                            if os.path.exists(BRAIN_OUTPUT): os.remove(BRAIN_OUTPUT)
                            search_payload = {
                                "_protocol": load_brain_protocol(),
                                "tab_id": tab_id,
                                "query": session.get("user_query"),
                                "search_results": search_results,
                                "action_performed": action_name,
                                "screenshot_path": screenshot_rel_path,
                                "history": session["history"]
                            }

                            # Include relevant past fixes from knowledge base
                            obs_url = obs.get("url", "") if obs else ""
                            detected_scenario = session.get("detected_scenario", "")
                            relevant = find_relevant_fixes(detected_scenario, obs_url)
                            if relevant:
                                search_payload["relevant_fixes"] = relevant
                                logger.info(f"📚 KB match found: {len(relevant)} relevant past fix(es) fed to brain_input.json")

                            temp_input = f"{BRAIN_INPUT}.tmp"
                            with open(temp_input, "w", encoding="utf-8") as f:
                                json.dump(search_payload, f, indent=2)
                            os.replace(temp_input, BRAIN_INPUT)
                            brain_turn_counter += 1
                            with open(BRAIN_READY_FLAG, "w") as f:
                                f.write(str(brain_turn_counter))
                            logger.info(f"Search results written to {BRAIN_INPUT}, turn #{brain_turn_counter}, waiting for next Brain action...")

                            # Wait for the Brain's next response
                            while not os.path.exists(BRAIN_OUTPUT):
                                await asyncio.sleep(0.5)

                            retries = 5
                            while retries > 0:
                                try:
                                    action_data = read_json_file(BRAIN_OUTPUT)
                                    # SCRIPT TUNNEL: Handle code_file if specified
                                    if action_data.get("action") == "inject_js" and "payload" in action_data:
                                        payload = action_data["payload"]
                                        if "code_file" in payload:
                                            script_filename = os.path.basename(payload["code_file"])
                                            script_abs = os.path.join(SERVER_DIR, script_filename)
                                            if os.path.exists(script_abs):
                                                with open(script_abs, "r", encoding="utf-8") as sf:
                                                    payload["code"] = sf.read()
                                                os.remove(script_abs)
                                            else:
                                                logger.error(f"code_file not found: {script_abs} — inject_js will fail")
                                                if "code" not in payload:
                                                    payload["code"] = f"console.error('TS Sidekick: code_file not found: {script_filename}');"
                                    os.remove(BRAIN_OUTPUT)
                                    break
                                except (json.JSONDecodeError, PermissionError) as e:
                                    retries -= 1
                                    if retries == 0:
                                        logger.error(f"Malformed JSON in brain_output.json (search loop): {e}")
                                        raw_output = ""
                                        try:
                                            with open(BRAIN_OUTPUT, "r", encoding="utf-8") as f:
                                                raw_output = f.read()[:500]
                                        except Exception:
                                            raw_output = "(could not read raw content)"
                                        if os.path.exists(BRAIN_OUTPUT): os.remove(BRAIN_OUTPUT)
                                        error_payload = {
                                            "_protocol": load_brain_protocol(),
                                            "tab_id": tab_id,
                                            "query": session.get("user_query"),
                                            "error": {
                                                "type": "MALFORMED_JSON",
                                                "message": f"Your last brain_output.json was not valid JSON. Parse error: {str(e)}",
                                                "raw_output_preview": raw_output,
                                                "instructions": "You MUST write valid JSON to server/brain_output.json. Check for: unescaped quotes inside strings, missing commas, line breaks in string values (use \\n instead), and unclosed braces. See the Technical Schema and examples in the protocol above. Try your last action again with properly formatted JSON."
                                            },
                                            "screenshot_path": screenshot_rel_path,
                                            "history": session["history"]
                                        }
                                        temp_input = f"{BRAIN_INPUT}.tmp"
                                        with open(temp_input, "w", encoding="utf-8") as f:
                                            json.dump(error_payload, f, indent=2)
                                        os.replace(temp_input, BRAIN_INPUT)
                                        brain_turn_counter += 1
                                        with open(BRAIN_READY_FLAG, "w") as f:
                                            f.write(str(brain_turn_counter))
                                        logger.info(f"JSON error feedback written to {BRAIN_INPUT}, turn #{brain_turn_counter}")
                                        while not os.path.exists(BRAIN_OUTPUT):
                                            await asyncio.sleep(0.5)
                                        retries = 5
                                        continue
                                    else:
                                        await asyncio.sleep(0.2)
                                except Exception as e:
                                    logger.error(f"Unexpected error in brain_output.json (search loop): {e}")
                                    raw_output = ""
                                    try:
                                        with open(BRAIN_OUTPUT, "r", encoding="utf-8") as f:
                                            raw_output = f.read()[:500]
                                    except Exception:
                                        raw_output = "(could not read raw content)"
                                    if os.path.exists(BRAIN_OUTPUT): os.remove(BRAIN_OUTPUT)
                                    error_payload = {
                                        "_protocol": load_brain_protocol(),
                                        "tab_id": tab_id,
                                        "query": session.get("user_query"),
                                        "error": {
                                            "type": "MALFORMED_JSON",
                                            "message": f"Your last brain_output.json caused an error: {str(e)}",
                                            "raw_output_preview": raw_output,
                                            "instructions": "You MUST write valid JSON to server/brain_output.json. Check for: unescaped quotes inside strings, missing commas, line breaks in string values (use \\n instead), and unclosed braces. See the Technical Schema and examples in the protocol above. Try your last action again with properly formatted JSON."
                                        },
                                        "screenshot_path": screenshot_rel_path,
                                        "history": session["history"]
                                    }
                                    temp_input = f"{BRAIN_INPUT}.tmp"
                                    with open(temp_input, "w", encoding="utf-8") as f:
                                        json.dump(error_payload, f, indent=2)
                                    os.replace(temp_input, BRAIN_INPUT)
                                    brain_turn_counter += 1
                                    with open(BRAIN_READY_FLAG, "w") as f:
                                        f.write(str(brain_turn_counter))
                                    logger.info(f"Error feedback written to {BRAIN_INPUT}, turn #{brain_turn_counter}")
                                    while not os.path.exists(BRAIN_OUTPUT):
                                        await asyncio.sleep(0.5)
                                    retries = 5
                                    continue

                            # Update action_name for the loop check
                            action_name = action_data.get('action')

                    if local_chain_count >= MAX_LOCAL_CHAINS:
                        logger.warning(f"Local action chain hit safety cap ({MAX_LOCAL_CHAINS})")
                        action_data = {"thought": "Too many consecutive search actions.", "action": "post_message", "payload": {"message": "Hit the local action chain limit. Try a browser action next."}}
                        action_name = "post_message"

                    # ── BROWSER ACTION → EXTENSION ────────────────────────
                    if action_name and action_name not in LOCAL_ACTIONS:
                        # Track fix attempts for inject_js and inject_css
                        if action_name in ("inject_js", "inject_css"):
                            attempt = record_fix_attempt(session, action_data)
                            logger.info(f"Fix attempt #{attempt['attempt_number']} recorded: {action_name}")

                        logger.info(f"Sending action to Extension: {action_name}")
                        await websocket.send_text(json.dumps({
                            "type": "action",
                            "tabId": tab_id,
                            "data": action_data
                        }))

    except WebSocketDisconnect:
        logger.info(f"Extension disconnected from {client_host}")
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
    finally:
        ping_task.cancel()
        logger.info("Keepalive task cancelled.")

import threading
from PIL import Image
import pystray
import uvicorn
import sys
import ctypes
import socket as socket_lib

def is_port_in_use(port):
    with socket_lib.socket(socket_lib.AF_INET, socket_lib.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def kill_stale_server(port):
    import subprocess
    try:
        output = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True).decode()
        for line in output.strip().split('\n'):
            if 'LISTENING' in line:
                pid = line.strip().split()[-1]
                logger.info(f"Killing stale server process {pid}...")
                subprocess.run(f"taskkill /F /PID {pid}", shell=True)
    except Exception:
        pass

def run_server():
    if os.path.exists(BRAIN_INPUT): os.remove(BRAIN_INPUT)
    if os.path.exists(BRAIN_OUTPUT): os.remove(BRAIN_OUTPUT)
    
    if is_port_in_use(8000):
        logger.info("Port 8000 in use. Cleaning up...")
        kill_stale_server(8000)
        import time
        time.sleep(1)

    logger.info("Starting FastAPI server...")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

def on_quit(icon, item):
    icon.stop()
    logger.info("Stopping Server...")
    os._exit(0)

def view_logs(icon, item):
    import subprocess
    if os.path.exists(log_file):
        subprocess.run(f"notepad.exe {log_file}", shell=True)

def setup_tray():
    icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
    image = Image.open(icon_path) if os.path.exists(icon_path) else Image.new('RGB', (64, 64), color=(34, 197, 94))
    
    menu = pystray.Menu(
        pystray.MenuItem("TS Sidekick Server (Running)", lambda: None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("View Logs", view_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", on_quit)
    )
    
    icon = pystray.Icon("ts_sidekick", image, "TS Sidekick Server", menu)
    icon.run()

if __name__ == "__main__":
    try:
        logger.info("Server application starting...")
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        setup_tray()
    except Exception as e:
        logger.error(f"CRITICAL STARTUP ERROR: {e}", exc_info=True)
        with open(os.path.join(SERVER_DIR, "crash_report.txt"), "w") as f:
            f.write(str(e))
        os._exit(1)
