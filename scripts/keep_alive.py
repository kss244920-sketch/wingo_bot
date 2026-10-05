#!/usr/bin/env python3
import json
import os
import sys
import datetime
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests library not found. Please install requests.")
    sys.exit(1)

APP_NAME = "Git r_y6SKa3r"
APP_ID = 66236

# Embedded fallback token for autonomous 24/7 cloud execution
FALLBACK_TOKEN = (
    "CfDJ8OJj33e2MidEmv/zWgEBADNUw7OdbOSG/SN15LsqRvdv0ce/eLRmu+yzk3pLUPqkayf5jPMncfuss9xYfTSqpppcU4I6m8ORBu1Tijcl1Z9Zsop"
    "GrqZ+2c9rePPWibQHKgwnQ/Jdgshwzm1tVx82Wy6BnRzdme3MHLtKairf2eN9A2+2XYNfC95Wbn0o6C4+KnMiwv2n2jnLY30wcU+a3v/bS1MwuMzS"
    "QGbZzQt/R08Xuww9boLoOZiG7CorLSJlM2OeduA7tqyDuBF7m0pcDt2JUDVhHHVZEbzKHpON71Hhpz88U9o2mT1y0z9fqBHz0dW95bNFuwWx2b2qMD"
    "NM51ld1umPLj2R9Txw5RiGjbao5S4Acv/rYbeFiX4b7UKIgEkOTEFaBspiGrN81P5XpRPgOH8oKsRYyqsjxHC/YWumy8WZr4/GcxWo2/aN9TVvE0ZT"
    "Z3EBmuwVW+7ipt3T0Sa90jwmfvggwcoGIDxbd1hS+8j9w2rzPYJp+7r+s3IWFvwjsxcRj5+OL8bcpFqF5bNDDb7CbgcatUynDp9JLIulZkiL/3GZ8F"
    "RUj2+4Qy0KrKGDDgAyjKzUUqAqjjlKvSveMEIY8gK6dnn8SZv1VDjSkHDnQ9LMROLM/bXFhLDLP9GDn1IRiqOwsRhsVhWFJlFFMRRQ8OTB4TknKHXq"
    "tcsFxIyEDMQLS+z8dy8Q4Ol1dumEWY3DVGPumWBn969/6xQPNNAp96Cb89BZP56gX2MsvqNIt+D01MTQUm+AUJpOLMulrf2vEIte+Ns17RFAshECak"
    "Cy4rJ8QbUoxo8hjmYMIxF7HxmjOQciqRyEZ8OH6jBN+yQptPIbts+KQmL3fUPWlv5oSCNCwQ1Jc6+o27++"
)

def get_mcp_config():
    # 1. Environment variable (e.g. GitHub Actions secret)
    env_identity = os.environ.get("JRNM_IDENTITY")
    if env_identity:
        return {
            "url": "https://justrunmy.app/api/mcp",
            "headers": {"X-User-Identity": env_identity.strip(), "Content-Type": "application/json"}
        }

    # 2. Token candidate files
    token_candidates = [
        Path(__file__).parent.parent / "jrnm_identity.token",
        Path(__file__).parent / "jrnm_identity.token",
        Path.home() / "wingo_bot/jrnm_identity.token",
        Path.home() / "Downloads/mcp(4).json",
        Path.home() / "Downloads/mcp(3).json",
        Path.home() / ".gemini/config/mcp_config.json",
    ]
    for p in token_candidates:
        if p.exists() and p.stat().st_size > 0:
            try:
                if p.suffix == ".json":
                    with open(p) as f:
                        cfg = json.load(f)
                        tok = cfg.get("mcpServers", {}).get("justrunmy.app", {}).get("headers", {}).get("X-User-Identity")
                        if tok:
                            return {
                                "url": "https://justrunmy.app/api/mcp",
                                "headers": {"X-User-Identity": tok.strip(), "Content-Type": "application/json"}
                            }
                else:
                    tok = p.read_text(encoding="utf-8").strip()
                    if tok:
                        return {
                            "url": "https://justrunmy.app/api/mcp",
                            "headers": {"X-User-Identity": tok, "Content-Type": "application/json"}
                        }
            except Exception:
                pass

    # 3. Fallback to hardcoded embedded token
    return {
        "url": "https://justrunmy.app/api/mcp",
        "headers": {"X-User-Identity": FALLBACK_TOKEN, "Content-Type": "application/json"}
    }

def call_mcp_tool(server_conf, tool_name, arguments=None):
    url = server_conf["url"]
    headers = server_conf.get("headers", {})
    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time()),
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments or {}
        }
    }
    last_err = None
    for attempt in range(5):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=25)
            r.raise_for_status()
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    line_data = line[5:].strip()
                    if not line_data:
                        continue
                    data = json.loads(line_data)
                    content = data.get("result", {}).get("content", [])
                    if content and "text" in content[0]:
                        raw_text = content[0]["text"]
                        try:
                            return json.loads(raw_text)
                        except Exception:
                            return raw_text
            return None
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < 4:
                print(f"[Attempt {attempt+1}/5] Connection error ({e}). Retrying in 8s...")
                time.sleep(8)
            else:
                raise last_err
    return None

def parse_ping_left_hours(ping_left_str):
    if not ping_left_str:
        return 999.0
    try:
        clean = ping_left_str.strip()
        if clean.startswith("-"):
            return -1.0
        parts = clean.split(":")
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
        print(f"Could not parse ping_left '{ping_left_str}': {e}")
    return 999.0

def main():
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] 🚀 Running WinGo Bot JustRunMy.App Keep-Alive Check...")

    server_conf = get_mcp_config()
    if not server_conf:
        print("ERROR: Could not locate MCP credentials for JustRunMy.App.")
        sys.exit(1)

    apps_data = call_mcp_tool(server_conf, "jrnm_get_user_apps")
    if not apps_data or "result" not in apps_data:
        print("Failed to retrieve applications list from JustRunMy.App.")
        sys.exit(1)

    items = apps_data.get("result", {}).get("items", [])
    target_app = None
    for app in items:
        if app.get("id") == APP_ID or app.get("name") == APP_NAME:
            target_app = app
            break

    if not target_app:
        print(f"Target app (ID {APP_ID} / '{APP_NAME}') not found in account!")
        sys.exit(1)

    is_started = target_app.get("isStarted", False)
    properties = {p["name"]: p["value"] for p in target_app.get("properties", []) if "name" in p and "value" in p}

    ping_left_str = properties.get("com.jrnm.computed.ping_left", "")
    hours_left = parse_ping_left_hours(ping_left_str)

    print(f"App: '{target_app.get('name')}' (ID: {target_app.get('id')})")
    print(f"Status: isStarted={is_started}, Lease Left={hours_left:.2f}h (Raw: '{ping_left_str}')")

    needs_action = False
    action_reason = ""

    if not is_started:
        needs_action = True
        action_reason = "WinGo Bot container is currently STOPPED."
    elif hours_left < 8.0:
        needs_action = True
        action_reason = f"Free tier lease timer is low ({hours_left:.2f}h remaining < 8.0h threshold). Proactively renewing 36h lease."

    if needs_action:
        print(f"⚡ Triggering Renewal Action because: {action_reason}")
        if is_started:
            call_mcp_tool(server_conf, "jrnm_stop_app", {"appId": target_app["id"]})
            time.sleep(3)
        res = call_mcp_tool(server_conf, "jrnm_start_or_restart_app", {"appId": target_app["id"]})
        print(f"Start Response: {res}")
        print("✅ Keep-Alive action completed successfully. WinGo Bot lease renewed!")
    else:
        print(f"✅ All good! WinGo Bot is running healthy with {hours_left:.2f}h lease remaining.")

if __name__ == "__main__":
    main()
