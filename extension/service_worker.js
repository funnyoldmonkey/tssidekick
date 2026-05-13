let socket = null;
let sidepanelPort = null;
let activeTabId = null;

// Persistent diagnostic storage
let diagnostics = {
    logs: [],
    network: []
};

let networkRequests = {};

// Ensure the side panel opens when the extension icon is clicked
chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((error) => console.error(error));

function connectSocket() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        return;
    }

    console.log("Attempting to connect to Sidecar...");
    socket = new WebSocket("ws://127.0.0.1:8000/ws");

    socket.onopen = () => {
        console.log("Connected to Sidecar");
        notifyStatus(true);
    };

    socket.onclose = (event) => {
        console.log("Disconnected from Sidecar:", event.reason);
        notifyStatus(false);
        socket = null;
        if (activeTabId) remove_glow(activeTabId).catch(() => {});
        setTimeout(connectSocket, 3000); 
    };

    socket.onerror = (error) => {
        console.error("WebSocket Error:", error);
    };

    socket.onmessage = async (event) => {
        const msg = JSON.parse(event.data);
        // Silently drop keepalive pings from server
        if (msg.type === "ping") return;
        if (msg.type === "command" && msg.action === "observe") {
            const observation = await captureObservation(parseInt(msg.tabId));
            if (sidepanelPort) sidepanelPort.postMessage({ type: "observation_update", data: observation });
            socket.send(jsonStr({
                type: "observation",
                tabId: msg.tabId,
                data: observation
            }));
        } else if (msg.type === "action") {
            if (sidepanelPort) sidepanelPort.postMessage({ type: "agent_response", data: msg.data });
            await performAction(parseInt(msg.tabId), msg.data);
            // Sidepanel updates on the next real observation turn — no redundant capture here
        } else if (msg.type === "error") {
            if (sidepanelPort) sidepanelPort.postMessage({ type: "agent_status", message: `Error: ${msg.message}` });
        }
    };
}

function notifyStatus(connected) {
    if (sidepanelPort) {
        sidepanelPort.postMessage({ type: "socket_status", connected });
    }
}

function jsonStr(obj) { return JSON.stringify(obj); }

// Debugger Event Handlers
chrome.debugger.onEvent.addListener((source, method, params) => {
    if (method === "Log.entryAdded") {
        const entry = params.entry;
        diagnostics.logs.push(`[${entry.level}] ${entry.text}`);
    } else if (method === "Runtime.consoleAPICalled") {
        const args = params.args.map(a => a.value || a.description).join(' ');
        diagnostics.logs.push(`[console] ${args}`);
    } else if (method === "Network.loadingFailed") {
        // Captures network-level failures: DNS errors, connection refused, CORS preflight blocks, timeouts
        const { requestId, errorText, type } = params;
        // Try to find the URL from a prior requestWillBeSent event (not always available)
        diagnostics.network.push(`🚨 FAILED: [${type || 'unknown'}] ${errorText} (network error — no HTTP response)`);
    } else if (method === "Network.responseReceived") {
        const { requestId, response } = params;
        if (response.status >= 400) {
            diagnostics.network.push(`🚨 FAILED: ${response.url} (${response.status})`);
        } else {
            const isInteresting = response.url.includes('/api/') || 
                                response.url.includes('.json') || 
                                response.url.includes('cart');
                                
            if (isInteresting) {
                networkRequests[response.url] = requestId;
                chrome.debugger.sendCommand({ tabId: source.tabId }, "Network.getResponseBody", { requestId }, (result) => {
                    if (result && result.body) {
                        const cleanUrl = response.url.split('?')[0].split('/').pop();
                        diagnostics.network.push(`📦 DATA [${cleanUrl}]: ${result.body}`);
                    }
                });
            } else {
                networkRequests[response.url] = requestId;
                diagnostics.network.push(`✅ SUCCESS: ${response.url.split('?')[0]} (${response.status})`);
            }
        }
    }
});

async function attachDebugger(tabId) {
    return new Promise((resolve) => {
        chrome.debugger.attach({ tabId }, "1.3", async () => {
            if (chrome.runtime.lastError) {
                console.warn("Debugger attach failed:", chrome.runtime.lastError.message);
                resolve(false);
            } else {
                chrome.debugger.sendCommand({ tabId }, "Network.enable");
                chrome.debugger.sendCommand({ tabId }, "Log.enable");
                chrome.debugger.sendCommand({ tabId }, "Runtime.enable");
                diagnostics.logs = [];
                diagnostics.network = [];

                await async_inject_glow(tabId);

                resolve(true);
            }
        });
    });
}

async function captureObservation(tabId) {
    if (sidepanelPort) sidepanelPort.postMessage({ type: "agent_status", message: "Capturing Deep Diagnostics..." });
    
    try {
        const results = await chrome.scripting.executeScript({
            target: { tabId },
            func: () => {
                const describe = (el) => {
                    const tag = el.tagName.toLowerCase();

                    // Script tags: capture src attribute (critical for app debugging)
                    if (tag === 'script') {
                        const src = el.src || el.getAttribute('src');
                        if (src) return `📜 [script] src="${src}"`;
                        // Inline scripts: show first 200 chars to identify them
                        const inline = (el.textContent || '').trim().substring(0, 200);
                        if (inline) return `📜 [script:inline] "${inline}..."`;
                        return null;
                    }
                    // Link/style tags: capture href (CSS debugging)
                    if (tag === 'link') {
                        const href = el.href || el.getAttribute('href');
                        const rel = el.rel || '';
                        if (href) return `🎨 [link rel="${rel}"] href="${href}"`;
                        return null;
                    }
                    // Style tags: note their presence and size
                    if (tag === 'style') {
                        const len = (el.textContent || '').length;
                        const id = el.id ? `#${el.id}` : '';
                        return `🎨 [style${id}] (${len} chars)`;
                    }

                    // Skip pure noise
                    if (['meta', 'noscript', 'br', 'hr'].includes(tag)) return null;

                    const id = el.id ? `#${el.id}` : '';
                    const cls = el.className && typeof el.className === 'string' ? `.${el.className.split(' ').join('.')}` : '';
                    const type = el.type ? `[type="${el.type}"]` : '';

                    const interactive = ["BUTTON", "A", "INPUT", "SELECT", "TEXTAREA"];
                    const hasClick = el.onclick || el.getAttribute('role') === 'button';
                    let isInteractive = interactive.includes(el.tagName) || hasClick;

                    // Full text for interactive elements, direct text only for containers
                    const text = (el.innerText || el.value || el.title || '').trim();
                    const directText = isInteractive ? text : Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .filter(t => t.length > 0)
                        .join(' ');

                    // Only check computed style on interactive elements and elements with content
                    // This avoids forcing layout reflow on every single DOM node
                    let visFlag = '';
                    if (isInteractive || id || directText) {
                        try {
                            const cs = window.getComputedStyle(el);
                            if (cs.display === 'none') visFlag = ' [HIDDEN:display]';
                            else if (cs.visibility === 'hidden') visFlag = ' [HIDDEN:visibility]';
                            else if (cs.opacity === '0') visFlag = ' [HIDDEN:opacity]';
                            else if (el.offsetWidth === 0 && el.offsetHeight === 0 && !isInteractive) visFlag = ' [HIDDEN:zero-size]';
                            // Check cursor:pointer only when we need to (deferred from above)
                            if (!isInteractive && cs.cursor === 'pointer') isInteractive = true;
                        } catch(e) {}
                    }

                    if (!directText && !isInteractive && !id && !visFlag) return null;

                    const marker = isInteractive ? '★' : '·';
                    return `${marker} [${tag}${id}${cls}${type}]${visFlag} "${directText}"`;
                };

                return {
                    dom: Array.from(document.querySelectorAll('*')).map(describe).filter(x => x !== null).join('\n'),
                    url: window.location.href
                };
            }
        });

        const pageData = results[0].result;

        // Snapshot current diagnostics then clear for next turn
        const allLogs = diagnostics.logs.join('\n') || "No console logs.";
        const allNetwork = diagnostics.network.join('\n') || "No network issues.";
        diagnostics.logs = [];
        diagnostics.network = [];

        let screenshot = null;
        try {
            const tab = await chrome.tabs.get(tabId);
            screenshot = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
        } catch (e) { console.warn("Screenshot failed:", e); }

        const elementCapture = diagnostics.element_capture;
        diagnostics.element_capture = null; // Consume it

        return {
            dom: pageData.dom,
            url: pageData.url,
            console: allLogs,
            network: allNetwork,
            screenshot: screenshot,
            element_view: elementCapture
        };
    } catch (e) {
        return { dom: "Error: Access denied.", console: e.message, network: "" };
    }
}

async function performAction(tabId, actionData) {
    const { action, payload } = actionData;
    
    try {
        if (action === "inject_js") {
            // Use chrome.debugger to bypass CSP and allow MAIN world access without eval() issues
            await new Promise((resolve) => {
                chrome.debugger.sendCommand({ tabId }, "Runtime.evaluate", {
                    expression: payload.code,
                    userGesture: true,
                    awaitPromise: true
                }, (result) => {
                    if (chrome.runtime.lastError) {
                        diagnostics.logs.push(`[error] Debugger injection failed: ${chrome.runtime.lastError.message}`);
                    } else if (result && result.exceptionDetails) {
                        const err = result.exceptionDetails.exception.description || "Unknown Error";
                        diagnostics.logs.push(`[error] Script exception: ${err}`);
                    }
                    resolve();
                });
            });
        } else if (action === "click") {
            const clickResult = await chrome.scripting.executeScript({
                target: { tabId },
                func: (sel) => {
                    const el = document.querySelector(sel);
                    if (el) {
                        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        el.style.outline = "5px solid #22c55e";
                        el.style.outlineOffset = "2px";
                        setTimeout(() => el.click(), 500);
                        return true;
                    }
                    return false;
                },
                args: [payload.selector]
            });
            if (clickResult && clickResult[0] && !clickResult[0].result) {
                diagnostics.logs.push(`[error] click: selector not found — "${payload.selector}"`);
            }
        } else if (action === "type") {
            const typeResult = await chrome.scripting.executeScript({
                target: { tabId },
                func: (sel, txt) => {
                    const el = document.querySelector(sel);
                    if (el) {
                        el.focus();
                        el.value = txt;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                    return false;
                },
                args: [payload.selector, payload.text]
            });
            if (typeResult && typeResult[0] && !typeResult[0].result) {
                diagnostics.logs.push(`[error] type: selector not found — "${payload.selector}"`);
            }
        } else if (action === "scroll") {
            await chrome.scripting.executeScript({
                target: { tabId },
                func: (x, y) => { window.scrollBy(x, y); },
                args: [payload.x || 0, payload.y || 0]
            });
        } else if (action === "navigate") {
            await chrome.tabs.update(tabId, { url: payload.url });
            await new Promise(r => {
                const l = (tId, changeInfo) => { if (tId === tabId && changeInfo.status === 'complete') { chrome.tabs.onUpdated.removeListener(l); r(); } };
                chrome.tabs.onUpdated.addListener(l);
            });
        } else if (action === "hover") {
            const hoverResult = await chrome.scripting.executeScript({
                target: { tabId },
                func: (sel) => {
                    const el = document.querySelector(sel);
                    if (el) {
                        el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                        el.style.outline = "2px dashed orange";
                        return true;
                    }
                    return false;
                },
                args: [payload.selector]
            });
            if (hoverResult && hoverResult[0] && !hoverResult[0].result) {
                diagnostics.logs.push(`[error] hover: selector not found — "${payload.selector}"`);
            }
        } else if (action === "inject_css") {
            await chrome.scripting.insertCSS({
                target: { tabId },
                css: payload.css
            });
        } else if (action === "get_network_body") {
            const requestId = networkRequests[payload.url];
            if (requestId) {
                const result = await new Promise(r => {
                    chrome.debugger.sendCommand({ tabId }, "Network.getResponseBody", { requestId }, (res) => r(res));
                });
                console.log(`>>> NETWORK_BODY [${payload.url}]:`, result ? result.body : "Failed to retrieve");
                diagnostics.logs.push(`>>> NETWORK_BODY [${payload.url}]: ${result ? result.body : "Failed"}`);
            } else {
                diagnostics.logs.push(`>>> NETWORK_BODY [${payload.url}]: NOT_FOUND (Request might be too old or filtered)`);
            }
        } else if (action === "clear_site_data") {
            const origin = new URL(payload.url || (await captureObservation(tabId)).url).origin;
            await chrome.browsingData.remove({
                origins: [origin]
            }, {
                "cache": true,
                "cookies": true,
                "localStorage": true
            });
            diagnostics.logs.push(`🧹 SITE DATA CLEARED: ${origin}`);



        } else if (action === "capture_element") {
            const rect = await chrome.scripting.executeScript({
                target: { tabId },
                func: (sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return { x: r.left, y: r.top, w: r.width, h: r.height, dpr: window.devicePixelRatio };
                },
                args: [payload.selector]
            });

            if (rect[0].result) {
                const { x, y, w, h, dpr } = rect[0].result;
                const tab = await chrome.tabs.get(tabId);
                const screenshot = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
                if (screenshot) {
                    diagnostics.logs.push(`🔍 ELEMENT CAPTURED: ${payload.selector} at ${x},${y}`);
                    diagnostics.element_capture = { selector: payload.selector, data: screenshot, x, y, w, h, dpr };
                }
            } else {
                diagnostics.logs.push(`[error] capture_element: selector not found — "${payload.selector}"`);
            }
        } else if (action === "click_at_position") {
            const posResult = await chrome.scripting.executeScript({
                target: { tabId },
                func: (x, y) => {
                    const el = document.elementFromPoint(x, y);
                    if (el) {
                        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        const dot = document.createElement('div');
                        dot.style.position = 'fixed';
                        dot.style.left = (x - 10) + 'px';
                        dot.style.top = (y - 10) + 'px';
                        dot.style.width = '20px';
                        dot.style.height = '20px';
                        dot.style.backgroundColor = '#22c55e';
                        dot.style.borderRadius = '50%';
                        dot.style.zIndex = '2147483647';
                        dot.style.pointerEvents = 'none';
                        document.documentElement.appendChild(dot);
                        setTimeout(() => {
                            el.click();
                            dot.remove();
                        }, 500);
                        return true;
                    }
                    return false;
                },
                args: [payload.x, payload.y]
            });
            if (posResult && posResult[0] && !posResult[0].result) {
                diagnostics.logs.push(`[error] click_at_position: no element found at (${payload.x}, ${payload.y})`);
            } else {
                diagnostics.logs.push(`🖱️ CLICK AT POSITION: ${payload.x}, ${payload.y}`);
            }
        } else if (action === "inspect_element") {
            const data = await chrome.scripting.executeScript({
                target: { tabId },
                func: (sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return "NOT_FOUND";
                    const r = el.getBoundingClientRect();
                    const computed = window.getComputedStyle(el);
                    return {
                        tag: el.tagName,
                        id: el.id,
                        classes: el.className,
                        value: el.value,
                        rect: { x: r.left, y: r.top, w: r.width, h: r.height },
                        styles: {
                            display: computed.display,
                            visibility: computed.visibility,
                            opacity: computed.opacity,
                            color: computed.color,
                            fontSize: computed.fontSize,
                            zIndex: computed.zIndex
                        },
                        attributes: Array.from(el.attributes).reduce((acc, attr) => {
                            acc[attr.name] = attr.value;
                            return acc;
                        }, {})
                    };
                },
                args: [payload.selector]
            });
            if (data[0].result === "NOT_FOUND") {
                diagnostics.logs.push(`[error] inspect_element: selector not found — "${payload.selector}"`);
            }
            diagnostics.logs.push(`>>> INSPECT [${payload.selector}]: ${JSON.stringify(data[0].result)}`);
        } else if (action === "post_message") {
            // Forward message to user via sidepanel
            if (sidepanelPort) sidepanelPort.postMessage({ type: "agent_message", text: payload.message });
            diagnostics.logs.push(`>>> AGENT MESSAGE: ${payload.message}`);
        } else if (action === "run_test") {
            const result = await new Promise((resolve) => {
                chrome.debugger.sendCommand({ tabId }, "Runtime.evaluate", {
                    expression: `(function(){ try { ${payload.code} \n return { success: true, message: "Test Passed" }; } catch(e) { return { success: false, message: e.message }; } })()`,
                    returnByValue: true
                }, (res) => {
                    if (chrome.runtime.lastError) resolve({ success: false, message: chrome.runtime.lastError.message });
                    else resolve(res.result.value);
                });
            });
            diagnostics.logs.push(`>>> TEST_RESULT: ${JSON.stringify(result)}`);
        } else if (action === "answer_user") {
            // V1 Compatibility
            if (sidepanelPort) sidepanelPort.postMessage({ type: "agent_message", text: payload.message });
        }
    } catch (e) {
        console.error("Action execution failed:", e);
        diagnostics.logs.push(`[error] Action ${action} failed: ${e.message}`);
    }

    // Keep the loop continuous even after messaging
    if (action === "answer_user" || action === "post_message") {
         // We might want to wait for user input here, but for now let's just observe after a delay
         await new Promise(r => setTimeout(r, 5000));
    } else {
        await new Promise(r => setTimeout(r, 2500));
    }

    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(jsonStr({
            type: "observation",
            tabId: tabId,
            data: await captureObservation(tabId)
        }));
    }
}

chrome.runtime.onConnect.addListener((p) => {
    if (p.name !== "sidepanel") return;
    sidepanelPort = p;
    
    sidepanelPort.onDisconnect.addListener(() => {
        console.log("Sidepanel closed, cleaning up...");
        if (activeTabId) {
            remove_glow(activeTabId);
            chrome.debugger.detach({ tabId: activeTabId }).catch(() => {});
        }
        sidepanelPort = null;
        activeTabId = null;
    });

    sidepanelPort.onMessage.addListener(async (msg) => {
        if (msg.type === "check_status") {
            notifyStatus(socket && socket.readyState === WebSocket.OPEN);
        } else if (msg.type === "start_agent") {
            activeTabId = msg.tabId;
            const rules = await chrome.declarativeNetRequest.getDynamicRules();
            const ruleIds = rules.map(r => r.id);
            if (ruleIds.length > 0) await chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds: ruleIds }).catch(() => {});

            await attachDebugger(activeTabId);
            async_inject_glow(activeTabId);
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(jsonStr({
                    type: "init",
                    tabId: msg.tabId,
                    query: msg.query,
                    model: msg.model
                }));
            } else {
                sidepanelPort.postMessage({ type: "agent_status", message: "Error: Not connected to Sidecar. Restart server." });
            }
        }
    });
});

async function async_inject_glow(tabId) {
    if (!tabId) return;
    try {
        await chrome.scripting.insertCSS({
            target: { tabId },
            css: `
                @keyframes pulse-ts-glow { 
                    0% { box-shadow: inset 0 0 15px rgba(34, 197, 94, 0.4); border-color: rgba(34, 197, 94, 0.5); } 
                    50% { box-shadow: inset 0 0 30px rgba(34, 197, 94, 0.8); border-color: rgba(34, 197, 94, 0.9); } 
                    100% { box-shadow: inset 0 0 15px rgba(34, 197, 94, 0.4); border-color: rgba(34, 197, 94, 0.5); } 
                }
                #ts-active-border {
                    position: fixed !important;
                    top: 0 !important;
                    left: 0 !important;
                    right: 0 !important;
                    bottom: 0 !important;
                    border: 4px solid rgba(34, 197, 94, 0.4) !important;
                    pointer-events: none !important;
                    z-index: 2147483647 !important;
                    animation: pulse-ts-glow 2s infinite !important;
                    display: block !important;
                }
            `
        });

        await chrome.scripting.executeScript({
            target: { tabId },
            func: () => {
                const id = 'ts-active-border';
                if (!document.getElementById(id)) {
                    const el = document.createElement('div');
                    el.id = id;
                    document.documentElement.appendChild(el);
                }
            }
        });
    } catch (e) { console.warn("Glow injection failed:", e); }
}

async function remove_glow(tabId) {
    if (!tabId) return;
    try {
        await chrome.scripting.executeScript({
            target: { tabId },
            func: () => {
                const el = document.getElementById('ts-active-border');
                if (el) el.remove();
            }
        });
    } catch (e) { console.warn("Glow removal failed:", e); }
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (tabId === activeTabId && changeInfo.status === 'complete') {
        console.log("Page refreshed/navigated, re-injecting glow...");
        async_inject_glow(tabId);
    }
});

connectSocket();

// ── Service Worker Keepalive ──────────────────────────────────────────────────
// Chrome suspends service workers after ~5 min of inactivity, killing the
// WebSocket. We use a chrome.alarms heartbeat every 20s to stay alive.
chrome.alarms.create("sw_keepalive", { periodInMinutes: 0.333 }); // ~20 seconds
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === "sw_keepalive") {
        // Touch something to keep the SW alive; also ensure socket stays connected
        if (!socket || socket.readyState === WebSocket.CLOSED) {
            connectSocket();
        }
    }
});
