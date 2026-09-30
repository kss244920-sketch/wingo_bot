#!/usr/bin/env python3
import json
import time
import requests
from pathlib import Path

APP_NAME = "Git r_y6SKa3r"
APP_ID = 66236
MCP_CONFIG = Path.home() / ".gemini/config/mcp_config.json"

def get_headers():
    if MCP_CONFIG.exists():
        with open(MCP_CONFIG) as f:
            cfg = json.load(f)
            return {
                "X-User-Identity": cfg["mcpServers"]["justrunmy.app"]["headers"]["X-User-Identity"],
                "Content-Type": "application/json"
            }
    raise RuntimeError("mcp_config.json not found")

def call_mcp(method_name, arguments=None):
    headers = get_headers()
    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time()),
        "method": "tools/call",
        "params": {
            "name": method_name,
            "arguments": arguments or {}
        }
    }
    r = requests.post("https://justrunmy.app/api/mcp", headers=headers, json=payload, timeout=20)
    for line in r.text.splitlines():
        if line.startswith("data: "):
            d = json.loads(line[6:])
            content = d.get("result", {}).get("content", [])
            if content and "text" in content[0]:
                try:
                    return json.loads(content[0]["text"])
                except Exception:
                    return content[0]["text"]
    return None

def parse_ping_left_hours(ping_left_str):
    if not ping_left_str:
        return 999.0
    try:
        if ping_left_str.startswith("-"):
            return -1.0
        parts = ping_left_str.split(":")
        if len(parts) >= 3:
            first = parts[0]
            if "." in first:
                days_str, hours_str = first.split(".")
                days = int(days_str)
                hours = int(hours_str)
            else:
                days = 0
                hours = int(first)
            minutes = int(parts[1])
            return (days * 24) + hours + (minutes / 60.0)
    except Exception as e:
        print(f"Could not parse ping_left: {e}")
    return 999.0

def check_and_renew():
    try:
        apps = call_mcp("jrnm_get_user_apps")
        items = apps.get("result", {}).get("items", []) if isinstance(apps, dict) else []
        target = None
        for it in items:
            if it.get("id") == APP_ID:
                target = it
                break

        if not target:
            print(f"[{time.ctime()}] App {APP_ID} not found in account!")
            return

        is_started = target.get("isStarted", False)
        ping_left = None
        for p in target.get("properties", []):
            if p.get("name") == "com.jrnm.computed.ping_left":
                ping_left = p.get("value")
                break

        hours_left = parse_ping_left_hours(ping_left)
        print(f"[{time.ctime()}] WinGo Cloud App: isStarted={is_started}, Lease Left={ping_left} (~{hours_left:.2f}h)")

        needs_action = False
        if not is_started:
            needs_action = True
            print(f"[{time.ctime()}] App is stopped! Triggering restart...")
        elif hours_left < 6.0:
            needs_action = True
            print(f"[{time.ctime()}] Free tier lease low (<6h remaining)! Triggering proactive renewal restart...")

        if needs_action:
            if is_started:
                call_mcp("jrnm_stop_app", {"appId": APP_ID})
                time.sleep(2)
            call_mcp("jrnm_start_or_restart_app", {"appId": APP_ID})
            print(f"[{time.ctime()}] Restart command sent successfully!")
        else:
            print(f"[{time.ctime()}] All good! App running healthy.")
    except Exception as e:
        print(f"[{time.ctime()}] Keep-alive error: {e}")

if __name__ == "__main__":
    check_and_renew()
