import json
import asyncio
import re
import os
import base64
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from gemma import gemma_client
import logging
import sys

# Setup logging to file
log_file = os.path.join(os.path.dirname(__file__), "server.log")
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

# File paths for Antigravity Brain mode
BRAIN_INPUT = "brain_input.json"
BRAIN_OUTPUT = "brain_output.json"

SYSTEM_PROMPT = """You are TS Sidekick, a Tier 2 Support Agent and expert troubleshooter.
You are running as an autonomous browser agent. Your goal is to identify and fix bugs in the current web page.

You will receive:
1. Simplified DOM (Actionable Markdown)
2. Console Logs (errors/warnings)
3. Network Data (failed requests/API calls)
4. URL of the current page

Respond ONLY with a JSON object in this format:
{
  "thought": "Internal scratchpad.",
  "action": "click" | "type" | "inject_js" | "navigate" | "scroll" | "hover" | "answer_user",
  "payload": {
    "selector": "css selector (for click/type/hover)",
    "text": "text to type",
    "code": "javascript to inject",
    "url": "url to navigate to",
    "x": 0, "y": 500, (for scroll)
    "message": "Final answer to user"
  }
}
"""

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
            with open("heartbeat.txt", "w") as f: f.write(f"Received message at {asyncio.get_event_loop().time()}")
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
                    
                    # Handle Screenshot
                    if "screenshot" in obs and obs["screenshot"]:
                        try:
                            header, encoded = obs["screenshot"].split(",", 1)
                            with open("current_view.png", "wb") as f:
                                f.write(base64.b64decode(encoded))
                            logger.info("Screenshot saved to server/current_view.png")
                        except Exception as e:
                            logger.error(f"Failed to save screenshot: {e}")

                    # Ensure no stale output exists
                    if os.path.exists(BRAIN_OUTPUT): os.remove(BRAIN_OUTPUT)
                    
                    with open(BRAIN_INPUT, "w", encoding="utf-8") as f:
                        json.dump({
                            "tab_id": tab_id,
                            "query": user_query,
                            "observation": obs,
                            "history": session["history"]
                        }, f, indent=2)

                    logger.info("Waiting for Antigravity Brain response (brain_output.json)...")
                    
                    while not os.path.exists(BRAIN_OUTPUT):
                        await asyncio.sleep(0.5)
                    
                    # Robust read with retries to avoid race conditions
                    retries = 5
                    while retries > 0:
                        try:
                            with open(BRAIN_OUTPUT, "r", encoding="utf-8") as f:
                                action_data = json.load(f)
                            
                            # SCRIPT TUNNEL: Handle code_file if specified
                            if action_data.get("action") == "inject_js" and "payload" in action_data:
                                payload = action_data["payload"]
                                if "code_file" in payload:
                                    script_path = payload["code_file"]
                                    script_filename = os.path.basename(script_path)
                                    if os.path.exists(script_filename):
                                        with open(script_filename, "r", encoding="utf-8") as sf:
                                            payload["code"] = sf.read()
                                        logger.info(f"Tunneling script from {script_filename}...")
                                        os.remove(script_filename)
                            
                            os.remove(BRAIN_OUTPUT)
                            os.remove(BRAIN_INPUT)
                            break # Success
                        except (json.JSONDecodeError, PermissionError) as e:
                            retries -= 1
                            if retries == 0:
                                logger.error(f"Error reading brain_output.json after retries: {e}")
                                action_data = {"thought": "Error reading brain file.", "action": "answer_user", "payload": {"message": f"Tunnel error: {str(e)}"}}
                                if os.path.exists(BRAIN_OUTPUT): os.remove(BRAIN_OUTPUT)
                                if os.path.exists(BRAIN_INPUT): os.remove(BRAIN_INPUT)
                            else:
                                await asyncio.sleep(0.2)
                        except Exception as e:
                            logger.error(f"Unexpected error reading brain_output.json: {e}")
                            action_data = {"thought": "Error reading brain file.", "action": "answer_user", "payload": {"message": f"Tunnel error: {str(e)}"}}
                            if os.path.exists(BRAIN_OUTPUT): os.remove(BRAIN_OUTPUT)
                            if os.path.exists(BRAIN_INPUT): os.remove(BRAIN_INPUT)
                            break

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
        with open("crash_report.txt", "w") as f:
            f.write(str(e))
        os._exit(1)
