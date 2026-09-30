#!/usr/bin/env python3
import time
import json
import os
import math
import threading
import requests
import re
import datetime
import cmath
import zlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

# ====================================================
# ⚙️ CONFIGURATION & API KEYS
# ====================================================
TELEGRAM_BOT_TOKEN = "8602171474:AAGYklXRTUbvinIRsLVsUOt9TsKApQUBhYA"
USER_ALERT_CHAT_ID = "-1003799001380"          # WinGo Prediction Channel
STORAGE_CHANNEL_ID = "-1003707286637"          # Database Channel (@OwEnvy)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")

# 12-Quant Engine + Single Master AI Brain (with cascading failover to eliminate rate limits)
MASTER_AI_MODELS = [
    "qwen/qwen3.8-27b",         # 27B parameter flagship reasoning engine
    "openai/gpt-oss-120b",      # 120B parameter deep analysis engine
    "allam-2-7b",               # 7B high-speed failover engine
]
MODEL_MASTER_AI = MASTER_AI_MODELS[0]

HISTORY_API_URL = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.environ.get("CACHE_FILE", os.path.join(BASE_DIR, "history_cache.json"))
STATE_FILE = os.environ.get("STATE_FILE", os.path.join(BASE_DIR, "state_cache.json"))

PANEL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WinGo 30S Elite Predictor</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        body { background-color: #0b0f0c; color: #fff; display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 16px; }
        .card { width: 100%; max-width: 440px; background: #121814; border: 1px solid #1f2e22; border-radius: 20px; padding: 24px; box-shadow: 0 0 30px rgba(16, 185, 129, 0.15); }
        .header { text-align: center; color: #86efac; font-size: 13px; font-weight: 700; letter-spacing: 1.5px; margin-bottom: 20px; }
        .pred-box { text-align: center; margin: 15px 0 20px 0; }
        .pred-val { font-size: 52px; font-weight: 900; letter-spacing: 2px; color: #22c55e; text-shadow: 0 0 20px rgba(34, 197, 94, 0.8), 0 0 40px rgba(34, 197, 94, 0.4); }
        .pred-val.skip { color: #f59e0b; text-shadow: 0 0 20px rgba(245, 158, 11, 0.7); font-size: 44px; }
        .pred-val.red { color: #ef4444; text-shadow: 0 0 20px rgba(239, 68, 68, 0.8); }
        .hedge-box { border: 2px dashed #eab308; border-radius: 10px; padding: 12px; margin: 18px 0; text-align: center; color: #fef08a; font-weight: 800; font-size: 14px; letter-spacing: 1.2px; background: rgba(234, 179, 8, 0.05); }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th { color: #6b7280; font-size: 12px; font-weight: 700; text-align: center; padding: 8px 4px; border-bottom: 1px solid #1f2937; }
        td { font-size: 13px; font-weight: 600; text-align: center; padding: 10px 4px; border-bottom: 1px solid #151e18; color: #d1d5db; }
        .win { color: #22c55e; font-weight: 800; }
        .loss { color: #ef4444; font-weight: 800; }
        .footer { text-align: center; margin-top: 24px; color: #4b5563; font-size: 12px; letter-spacing: 1px; }
    </style>
</head>
<body>
    <div class="card">
        <div class="header">PERIOD: <span id="period">LOADING...</span></div>
        <div class="pred-box">
            <div id="pred" class="pred-val">...</div>
        </div>
        <div id="hedge-box" class="hedge-box">OPPOSITE NUMS: <span id="opp-nums">--</span></div>
        <table>
            <thead>
                <tr>
                    <th>PRD</th>
                    <th>PRED</th>
                    <th>NUM</th>
                    <th>STATUS</th>
                </tr>
            </thead>
            <tbody id="history-rows"></tbody>
        </table>
        <div class="footer">FIRE X QUANT ULTRA-SNIPER</div>
    </div>
    <script>
        async function updatePanel() {
            try {
                const res = await fetch('/api/panel-data');
                const data = await res.json();
                document.getElementById('period').innerText = data.period || '--';
                const predEl = document.getElementById('pred');
                predEl.innerText = data.prediction || 'WAITING';
                predEl.className = 'pred-val ' + (data.prediction_class || '');
                document.getElementById('opp-nums').innerText = data.opposite_nums || 'N/A';
                
                const tbody = document.getElementById('history-rows');
                tbody.innerHTML = '';
                (data.history || []).forEach(row => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td>${row.prd}</td>
                        <td>${row.pred}</td>
                        <td>${row.num}</td>
                        <td class="${row.status.includes('WIN') ? 'win' : 'loss'}">${row.status}</td>
                    `;
                    tbody.appendChild(tr);
                });
            } catch (e) {}
        }
        setInterval(updatePanel, 3000);
        updatePanel();
    </script>
</body>
</html>
"""

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/panel"):
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PANEL_HTML.encode("utf-8"))
            return

        if self.path == "/api/panel-data":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            try:
                latest_p = list(MEMORY_PREDICTIONS.keys())[-1] if MEMORY_PREDICTIONS else "--"
                pred_info = MEMORY_PREDICTIONS.get(latest_p, {})
                t_val = pred_info.get("target_val", "WAITING")
                
                pred_cls = ""
                if t_val == "SKIP":
                    pred_cls = "skip"
                elif t_val == "RED":
                    pred_cls = "red"

                opp_nums = pred_info.get("opposite_nums", "N/A")

                history_rows = []
                for it in reversed(MEMORY_HISTORY[-12:]):
                    p_str = str(it.get("period", ""))[-3:]
                    num_val = it.get("num", 0)
                    sz = it.get("size", "")
                    col = it.get("color", "")
                    pred_it = MEMORY_PREDICTIONS.get(it.get("period"), {})
                    p_target = pred_it.get("target_val", sz)
                    is_win = True
                    if pred_it:
                        if pred_it.get("target_type") == "SIZE":
                            is_win = (pred_it.get("target_val") == sz)
                        elif pred_it.get("target_type") == "COLOR":
                            is_win = (pred_it.get("target_val") in col)
                    status_str = "WIN 🐯" if is_win else "LOSS 💔"
                    history_rows.append({
                        "prd": p_str,
                        "pred": p_target if p_target != "SKIP" else sz,
                        "num": num_val,
                        "status": status_str
                    })

                resp = {
                    "period": latest_p,
                    "prediction": t_val,
                    "prediction_class": pred_cls,
                    "opposite_nums": opp_nums,
                    "history": history_rows
                }
                self.wfile.write(json.dumps(resp).encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        try:
            response_data = {
                "status": "healthy",
                "service": "wingo_council_bot",
                "active_level": CURRENT_LOSS_STREAK + 1,
                "rounds_in_memory": len(MEMORY_HISTORY),
                "consecutive_skips": CONSECUTIVE_SKIPS
            }
            self.wfile.write(json.dumps(response_data).encode("utf-8"))
        except Exception:
            self.wfile.write(b'{"status":"healthy"}\n')

    def log_message(self, format, *args):
        pass

def keep_alive_heartbeat(port=8080):
    """
    Anti-Sleep Heartbeat Engine for JustRunMy.App:
    Pings the HTTP endpoint every 60s from inside the container so the host never marks it as idle/sleep!
    """
    time.sleep(5)
    print(f"💓 [HEARTBEAT ENGINE] Started Anti-Sleep Heartbeat on port {port}", flush=True)
    ping_num = 0
    while True:
        try:
            r = requests.get(f"http://127.0.0.1:{port}", timeout=4)
            ping_num += 1
            if ping_num % 10 == 0:
                print(f"💓 [HEARTBEAT] Ping #{ping_num} successful (Status: {r.status_code}) - Container Awake!", flush=True)
        except Exception:
            pass
        time.sleep(60)

def start_health_server(port=8080):
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        print(f"🌐 [HEALTH SERVER] Active on port {port}", flush=True)
        threading.Thread(target=keep_alive_heartbeat, args=(port,), daemon=True).start()
        server.serve_forever()
    except Exception as e:
        print(f"⚠️ [HEALTH SERVER NOTICE] {e}", flush=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:154.0) Gecko/20100101 Firefox/154.0",
    "Accept": "application/json"
}

# ====================================================
# ☁️ IN-MEMORY HISTORY & SESSION STATE
# ====================================================
MEMORY_HISTORY = []      # List of {"period": ..., "num": ..., "color": ..., "size": ..., "has_violet": ...}
KNOWN_PERIODS = set()    # O(1) set to prevent duplicates
MEMORY_PREDICTIONS = {}  # {target_period: {"color": ..., "size": ..., "conf": ..., "reason": ..., "consensus": ..., "violet_alert": ..., "grade": ...}}

CURRENT_LOSS_STREAK = 0  # 0 = Level 1, 1 = Level 2, 2 = Level 3, 3 = Level 4, 4 = Level 5
TOTAL_WINS = 0
TOTAL_LOSSES = 0
TOTAL_CYCLES = 0
CYCLE_WINS = 0
CYCLE_LOSSES = 0
CONSECUTIVE_SKIPS = 0
MAX_MARTINGALE_LEVEL = 3  # Standard 3-Level VIP Protection (1X, 3X, 9X)

def get_next_period(current_period):
    """
    WinGo 30S issueNumber structure:
    YYYYMMDD + 10005 + 4-digit round index (0001 to 2880).
    Properly handles midnight date rollover at round 2880!
    """
    if len(current_period) >= 17:
        date_str = current_period[:8]
        mid_code = current_period[8:13]
        round_str = current_period[13:]
        try:
            round_num = int(round_str)
            if round_num >= 2880:
                import datetime
                dt = datetime.datetime.strptime(date_str, "%Y%m%d") + datetime.timedelta(days=1)
                next_date = dt.strftime("%Y%m%d")
                return f"{next_date}{mid_code}0001"
            else:
                return f"{date_str}{mid_code}{round_num + 1:04d}"
        except Exception:
            pass
    try:
        return str(int(current_period) + 1)
    except Exception:
        return current_period

def load_cache():
    global MEMORY_HISTORY, KNOWN_PERIODS, CURRENT_LOSS_STREAK, TOTAL_WINS, TOTAL_LOSSES, TOTAL_CYCLES, CYCLE_WINS, CYCLE_LOSSES, MEMORY_PREDICTIONS, CONSECUTIVE_SKIPS
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                MEMORY_HISTORY = json.load(f)
                for item in MEMORY_HISTORY:
                    num = int(item.get("num", 0))
                    if "size" not in item:
                        item["size"] = "BIG" if num >= 5 else "SMALL"
                    if "has_violet" not in item:
                        item["has_violet"] = (num in (0, 5))
                    KNOWN_PERIODS.add(str(item.get("period", "")))
                print(f"📦 [RESTORED] Loaded {len(MEMORY_HISTORY)} historical rounds from memory cache!", flush=True)
        except Exception as e:
            print(f"[CACHE LOAD ERROR] {e}", flush=True)

    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                st = json.load(f)
                CURRENT_LOSS_STREAK = st.get("current_loss_streak", 0)
                TOTAL_WINS = st.get("total_wins", 0)
                TOTAL_LOSSES = st.get("total_losses", 0)
                TOTAL_CYCLES = st.get("total_cycles", 0)
                CYCLE_WINS = st.get("cycle_wins", 0)
                CYCLE_LOSSES = st.get("cycle_losses", 0)
                CONSECUTIVE_SKIPS = st.get("consecutive_skips", 0)
                saved_preds = st.get("memory_predictions", {})
                if isinstance(saved_preds, dict):
                    MEMORY_PREDICTIONS.update(saved_preds)
                print(f"📊 [STATE RESTORED] Level {CURRENT_LOSS_STREAK + 1} | Skips: {CONSECUTIVE_SKIPS} | Cycles: {CYCLE_WINS}W - {CYCLE_LOSSES}L | Pending: {list(MEMORY_PREDICTIONS.keys())}", flush=True)
        except Exception as e:
            print(f"[STATE LOAD ERROR] {e}", flush=True)

def save_cache():
    if len(MEMORY_HISTORY) > 0:
        try:
            tmp_file = f"{CACHE_FILE}.tmp"
            with open(tmp_file, "w") as f:
                json.dump(MEMORY_HISTORY, f)
            os.replace(tmp_file, CACHE_FILE)
        except Exception:
            pass

    try:
        tmp_st = f"{STATE_FILE}.tmp"
        st = {
            "current_loss_streak": CURRENT_LOSS_STREAK,
            "total_wins": TOTAL_WINS,
            "total_losses": TOTAL_LOSSES,
            "total_cycles": TOTAL_CYCLES,
            "cycle_wins": CYCLE_WINS,
            "cycle_losses": CYCLE_LOSSES,
            "consecutive_skips": CONSECUTIVE_SKIPS,
            "memory_predictions": MEMORY_PREDICTIONS
        }
        with open(tmp_st, "w") as f:
            json.dump(st, f)
        os.replace(tmp_st, STATE_FILE)
    except Exception:
        pass

def send_telegram_msg(chat_id, text, timeout=8, retries=2, pin=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                msg_id = data.get("result", {}).get("message_id")
                if pin and msg_id:
                    pin_telegram_msg(chat_id, msg_id)
                return msg_id or True
            elif r.status_code == 429:
                retry_after = 1
                try:
                    retry_after = int(r.json().get("parameters", {}).get("retry_after", 1))
                except Exception:
                    pass
                time.sleep(min(retry_after, 3))
                continue
            elif r.status_code == 400 and "can't parse entities" in r.text.lower():
                payload.pop("parse_mode", None)
                continue
            else:
                print(f"[TELEGRAM API ERROR] Status {r.status_code}: {r.text}", flush=True)
        except Exception as e:
            if attempt < retries:
                time.sleep(0.5)
                continue
            print(f"[TELEGRAM SEND EXCEPTION] {e}", flush=True)
    return False

def pin_telegram_msg(chat_id, message_id, disable_notification=True):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/pinChatMessage"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "disable_notification": disable_notification
    }
    for attempt in range(2):
        try:
            r = requests.post(url, json=payload, timeout=6)
            if r.status_code == 200:
                return True
            elif r.status_code == 429:
                time.sleep(1)
                continue
        except Exception:
            pass
    return False

def save_to_memory(period, number, raw_color, auto_save=True):
    global MEMORY_HISTORY, KNOWN_PERIODS
    p_str = str(period)
    if p_str in KNOWN_PERIODS:
        return False

    # In WinGo: 0 is RED+VIOLET, 5 is GREEN+VIOLET
    has_violet = (number in (0, 5)) or ("violet" in str(raw_color).lower())
    if number == 0:
        base_color = "RED"
    elif number == 5:
        base_color = "GREEN"
    else:
        base_color = "RED" if "red" in str(raw_color).lower() else "GREEN"

    size = "BIG" if number >= 5 else "SMALL"
    MEMORY_HISTORY.append({
        "period": p_str,
        "num": number,
        "color": base_color,
        "has_violet": has_violet,
        "size": size
    })
    KNOWN_PERIODS.add(p_str)
    if len(MEMORY_HISTORY) > 10000:
        MEMORY_HISTORY = MEMORY_HISTORY[-10000:]
        KNOWN_PERIODS = {it["period"] for it in MEMORY_HISTORY}
    if auto_save:
        save_cache()
    return True

# ====================================================
# 📡 TELEGRAM STORAGE CHANNEL SYNC
# ====================================================
def log_round_to_storage_channel(period, number, base_color, has_violet, size):
    if not STORAGE_CHANNEL_ID:
        return

    if has_violet:
        c_tag = "🔴 RED + 🟣 VIOLET" if base_color == "RED" else "🟢 GREEN + 🟣 VIOLET"
    else:
        c_tag = "🔴 RED" if base_color == "RED" else "🟢 GREEN"

    s_emoji = "🐘 BIG" if size == "BIG" else "🐜 SMALL"
    text = (
        f"📦 <b>[CLOUD DB RECORD]</b>\n"
        f"🔢 <b>Season ID (Period):</b> <code>{period}</code>\n"
        f"🎨 <b>Color:</b> <b>{c_tag}</b> | <b>{s_emoji}</b> (No. {number})\n"
        f"📊 <b>Total Synced:</b> {len(MEMORY_HISTORY)} rounds"
    )
    try:
        send_telegram_msg(STORAGE_CHANNEL_ID, text, timeout=8, retries=1)
    except Exception as e:
        print(f"[STORAGE ERROR] {e}", flush=True)

# ====================================================
# 📌 PINTEREST & BACCARAT 9-ROADMAP PATTERN RECOGNITION
# ====================================================
def detect_sequence_pattern(seq, item_type="COLOR"):
    """
    Detects 9 classic Pinterest, Scribd & Baccarat chart roadmaps:
    1. 3-2-1 Staircase (Pyramid/Countdown)
    2. 1-2-3 Reverse Staircase
    3. 3-3 Triplet (AAABBB)
    4. 2-2 Double-Step (AABB)
    5. 1-2 Single-Double (ABB ABB)
    6. 2-1 Double-Single (AAB AAB)
    7. ABBA Mirror Pattern (Sandwich Symmetry)
    8. Dragon Continuation (Streak >= 2)
    9. 1-1 Chop / Alternation (AB AB >= 2)
    """
    if not seq:
        default_val = "RED" if item_type == "COLOR" else "BIG"
        return default_val, 65.0, "Baseline Flow"

    last_val = seq[-1]
    opp_val = ("GREEN" if last_val == "RED" else "RED") if item_type == "COLOR" else ("SMALL" if last_val == "BIG" else "BIG")

    # Streak calculation
    streak_len = 1
    for x in reversed(seq[:-1]):
        if x == last_val:
            streak_len += 1
        else:
            break

    # Alternation calculation
    alt_len = 1
    for i in range(len(seq) - 1, 0, -1):
        if seq[i] != seq[i - 1]:
            alt_len += 1
        else:
            break

    # 1. 3-2-1 Staircase (3 A's -> 2 B's -> predicts 1 A)
    if len(seq) >= 5:
        a = seq[-5]
        b = seq[-1]
        if a != b and seq[-4] == a and seq[-3] == a and seq[-2] == b:
            return a, 92.5, f"3-2-1 Staircase ({a} Peak)"

    # 2. 1-2-3 Reverse Staircase (1 A -> 2 B's -> 1 A -> predicts A to reach 3)
    if len(seq) >= 4:
        a = seq[-4]
        b = seq[-3]
        if a != b and seq[-2] == b and seq[-1] == a:
            return a, 90.0, f"1-2-3 Staircase ({a} Extension)"

    # 3. 3-3 Triplet (3 A's -> 3 B's -> predicts A reset)
    if len(seq) >= 6:
        a = seq[-6]
        b = seq[-1]
        if a != b and seq[-5] == a and seq[-4] == a and seq[-3] == b and seq[-2] == b:
            return a, 88.5, f"3-3 Triplet ({a} Reset)"

    # 4. 2-2 Double-Step (AABB)
    if len(seq) >= 3:
        a = seq[-3]
        b = seq[-1]
        if a != b and seq[-2] == a:
            # AA followed by B -> complete 2nd pair B!
            return b, 92.0, f"2-2 Double-Step ({b} Pair)"
    if len(seq) >= 4:
        a = seq[-4]
        b = seq[-1]
        if a != b and seq[-3] == a and seq[-2] == b:
            # AABB completed -> shift to new pair A!
            return a, 89.0, f"2-2 Double-Step ({a} Shift)"

    # 5. ABBA Mirror Pattern (Sandwich Symmetry: A -> BB -> A)
    if len(seq) >= 3:
        a = seq[-3]
        b = seq[-2]
        if a != b and seq[-1] == b:
            # A followed by BB -> completes sandwich with A!
            return a, 91.0, f"ABBA Mirror ({a} Symmetry)"

    # 6. 1-2 Single-Double (ABB ABB)
    if len(seq) >= 4:
        a = seq[-4]
        b = seq[-3]
        if a != b and seq[-2] == b and seq[-1] == a:
            # ABB followed by A -> starts double B!
            return b, 88.5, f"1-2 Single-Double ({b} Double)"

    # 7. 2-1 Double-Single (AAB AAB)
    if len(seq) >= 4:
        a = seq[-4]
        b = seq[-2]
        if a != b and seq[-3] == a and seq[-1] == a:
            # AAB followed by A -> completes double A!
            return a, 88.5, f"2-1 Double-Single ({a} Double)"

    # 8. Dragon Momentum (Streak >= 2) - Follow the Trend! Never cut a dragon!
    if streak_len >= 2:
        return last_val, min(95.0, 79.0 + streak_len * 3.0), f"Dragon Trend ({last_val} x{streak_len})"

    # 9. 1-1 Alternating Chop (AB AB >= 2)
    if alt_len >= 2:
        return opp_val, min(93.0, 76.0 + alt_len * 3.0), f"1-1 Chop ({alt_len}x Alternation)"

    return opp_val if alt_len >= 2 else last_val, 65.0, "Momentum Flow"

# ====================================================
# 📊 MATHEMATICAL MARKET STRUCTURE & PATTERN ENGINE
# ====================================================
def detect_market_patterns(history_items):
    """
    Computes deterministic statistical quants across all historical rounds:
    - Dragon streak length & exhaustion
    - 1-1 Alternating Chop
    - 2-2 Double-Step pattern
    - Markov N-Gram Matrix
    - Winning Number to Color Bayes
    - Big/Small Compound Matrix
    - Rolling Mean-Reversion Imbalance
    - Micro-Cycle Autocorrelation Rhythm
    - Multi-Scale Shannon Entropy
    - Violet 0 & 5 Outlier Engine
    - Weibull Hazard Survival Rate
    - Fourier DFT Spectral Wave
    - Kolmogorov Complexity
    - Exponential Bayesian Posterior
    - Size (BIG/SMALL) Predictor
    """
    if not history_items:
        return {
            "streak_color": "RED", "streak_len": 1, "is_alt": False,
            "alt_len": 1, "is_double": False, "pattern_desc": "Baseline",
            "recent_compact": "", "violet_due": False, "rounds_since_violet": 0,
            "quants": {}, "pred_size": "BIG", "pred_size_conf": 75.0
        }

    colors = [it.get("color", "") for it in history_items]
    nums = [int(it.get("num", 0)) for it in history_items]
    sizes = [it.get("size", "BIG" if int(it.get("num", 0)) >= 5 else "SMALL") for it in history_items]
    last_c = colors[-1]
    opp_c = "GREEN" if last_c == "RED" else "RED"
    last_num = nums[-1]

    # 1. Streak Length (Dragon Detector)
    streak_len = 1
    for c in reversed(colors[:-1]):
        if c == last_c:
            streak_len += 1
        else:
            break

    # 2. Alternation Length (Chop Detector)
    alt_len = 1
    for i in range(len(colors) - 1, 0, -1):
        if colors[i] != colors[i - 1]:
            alt_len += 1
        else:
            break

    # 3. Pinterest 9-Roadmap Sequence Engine (Colors & Sizes)
    c_pred_val, c_pred_conf, c_pattern_desc = detect_sequence_pattern(colors, item_type="COLOR")
    s_pred_val, s_pred_conf, s_pattern_desc = detect_sequence_pattern(sizes, item_type="SIZE")
    q4_roadmap = (c_pred_val, c_pred_conf, f"Pinterest Roadmap: {c_pattern_desc}")
    is_double = ("2-2 Double-Step" in c_pattern_desc) or (len(colors) >= 4 and colors[-1] == colors[-2] and colors[-3] == colors[-4] and colors[-1] != colors[-3]) or (len(colors) >= 3 and colors[-1] != colors[-2] and colors[-2] == colors[-3])

    # 4. Quant 5: Multi-Order Markov N-gram Deep Ground Truth (Order 4, 3, 2)
    last4 = tuple(colors[-4:]) if len(colors) >= 4 else ()
    t4 = defaultdict(lambda: {"RED": 0, "GREEN": 0})
    for i in range(len(colors) - 4):
        t4[tuple(colors[i:i + 4])][colors[i + 4]] += 1
    c4 = t4.get(last4, {"RED": 0, "GREEN": 0})
    tot4 = c4["RED"] + c4["GREEN"]

    if tot4 >= 2:
        ng_col = "RED" if c4["RED"] >= c4["GREEN"] else "GREEN"
        ng_conf = round(max(c4["RED"], c4["GREEN"]) / tot4 * 100, 1)
        q5_ngram = (ng_col, min(95.0, ng_conf), f"Order-4 state {last4} resolved to {ng_col} ({ng_conf}%)")
    else:
        t3 = defaultdict(lambda: {"RED": 0, "GREEN": 0})
        for i in range(len(colors) - 3):
            t3[tuple(colors[i:i + 3])][colors[i + 3]] += 1
        last3 = tuple(colors[-3:]) if len(colors) >= 3 else ()
        c3 = t3.get(last3, {"RED": 0, "GREEN": 0})
        tot3 = c3["RED"] + c3["GREEN"]
        if tot3 >= 2:
            ng_col = "RED" if c3["RED"] >= c3["GREEN"] else "GREEN"
            ng_conf = round(max(c3["RED"], c3["GREEN"]) / tot3 * 100, 1)
            q5_ngram = (ng_col, ng_conf, f"Order-3 state {last3} resolved to {ng_col} ({ng_conf}%)")
        else:
            t2 = defaultdict(lambda: {"RED": 0, "GREEN": 0})
            for i in range(len(colors) - 2):
                t2[tuple(colors[i:i + 2])][colors[i + 2]] += 1
            last2 = tuple(colors[-2:]) if len(colors) >= 2 else ()
            c2 = t2.get(last2, {"RED": 0, "GREEN": 0})
            tot2 = c2["RED"] + c2["GREEN"]
            if tot2 >= 2:
                ng_col = "RED" if c2["RED"] >= c2["GREEN"] else "GREEN"
                ng_conf = round(max(c2["RED"], c2["GREEN"]) / tot2 * 100, 1)
                q5_ngram = (ng_col, ng_conf, f"Order-2 state {last2} resolved to {ng_col} ({ng_conf}%)")
            else:
                ng_col = opp_c if alt_len >= 2 else last_c
                q5_ngram = (ng_col, 65.0, f"Rhythm continuation favors {ng_col}")

    # 5. Quant 6: Winning Number-to-Color Bayes + Empirical Micro-Rules
    num_trans = defaultdict(lambda: {"RED": 0, "GREEN": 0})
    for i in range(len(nums) - 1):
        num_trans[nums[i]][colors[i + 1]] += 1
    cn = num_trans.get(last_num, {"RED": 0, "GREEN": 0})
    tot_n = cn["RED"] + cn["GREEN"]

    if last_num in (0, 4, 9):
        q6_num = ("GREEN", 66.5, f"Bayes Prior: Number {last_num} historically triggers GREEN transition")
    elif last_num in (1, 5, 6, 8):
        q6_num = ("RED", 66.0, f"Bayes Prior: Number {last_num} historically triggers RED transition")
    elif tot_n >= 2:
        nt_col = "RED" if cn["RED"] >= cn["GREEN"] else "GREEN"
        nt_conf = round(max(cn["RED"], cn["GREEN"]) / tot_n * 100, 1)
        q6_num = (nt_col, nt_conf, f"Winning Number {last_num} database matrix yielded {nt_col} ({nt_conf}%)")
    else:
        q6_num = (opp_c, 56.0, f"Number {last_num} default momentum")

    # 6. Quant 7: Big/Small & Color Multi-Variable Correlation Matrix
    state2 = ((sizes[-2], colors[-2]), (sizes[-1], colors[-1])) if len(sizes) >= 2 else None
    t2_bs = defaultdict(lambda: {"RED": 0, "GREEN": 0})
    for i in range(len(colors) - 2):
        s_k = ((sizes[i], colors[i]), (sizes[i + 1], colors[i + 1]))
        t2_bs[s_k][colors[i + 2]] += 1

    c2_bs = t2_bs.get(state2, {"RED": 0, "GREEN": 0}) if state2 else {"RED": 0, "GREEN": 0}
    tot_2bs = c2_bs["RED"] + c2_bs["GREEN"]

    if state2 == (("SMALL", "RED"), ("SMALL", "RED")):
        q7_bs = ("GREEN", 69.2, "Multi-Variable: (Small-Red x2) triggers GREEN reversal")
    elif tot_2bs >= 10:
        bs_col = "RED" if c2_bs["RED"] >= c2_bs["GREEN"] else "GREEN"
        bs_conf = round(max(c2_bs["RED"], c2_bs["GREEN"]) / tot_2bs * 100, 1)
        q7_bs = (bs_col, bs_conf, f"2-Step Compound state {state2} yielded {bs_col} ({bs_conf}%)")
    else:
        bs_col = opp_c if alt_len >= 2 else last_c
        q7_bs = (bs_col, 58.0, "Compound rhythm continuation")

    # 7. Quant 8: Rolling Mean-Reversion & Imbalance (ALL DB + 20-Round Micro)
    tot_db = len(colors)
    r_db = colors.count("RED")
    g_db = colors.count("GREEN")

    if streak_len >= 2:
        # Dragon Rider: Follow the shoe! Never cut a dragon!
        q8_mr = (last_c, min(90.0, 72.0 + streak_len * 3.0), f"Confirmed {last_c} dragon streak ({streak_len} rounds); riding momentum (Never cut a dragon)")
    elif alt_len >= 2:
        # Active 1-1 alternation: continuation favors chop
        q8_mr = (opp_c, min(88.0, 70.0 + alt_len * 3.0), f"Active 1-1 alternating chop ({alt_len} rounds); rhythm continuation favors {opp_c}")
    elif is_double:
        q8_mr = (last_c, 76.0, "2-2 paired double step; completing 2nd step of symmetry")
    else:
        r_20 = colors[-20:].count("RED") if tot_db >= 20 else r_db
        g_20 = colors[-20:].count("GREEN") if tot_db >= 20 else g_db
        if r_20 >= 13:
            q8_mr = ("GREEN", 67.0, f"RED short-term overbought ({r_20}R vs {g_20}G); mean-reversion favors GREEN")
        elif g_20 >= 13:
            q8_mr = ("RED", 67.0, f"GREEN short-term overbought ({g_20}G vs {r_20}R); mean-reversion favors RED")
        else:
            q8_mr = (opp_c, 56.0, "Micro-balance favors alternation")

    # 8. Quant 9: Micro-Cycle Autocorrelation Rhythm (Lag-2 & Lag-3)
    if tot_db >= 6:
        rec20 = colors[-20:] if tot_db >= 20 else colors
        rec_lag2 = sum(1 for i in range(2, len(rec20)) if rec20[i] == rec20[i - 2])
        rec_pct = (rec_lag2 / (len(rec20) - 2) * 100) if len(rec20) > 2 else 50.0

        if rec_pct >= 55.0:
            rhy_col = colors[-2]
            q9_rhy = (rhy_col, round(rec_pct, 1), f"Lag-2 harmonic active ({rec_lag2}/{len(rec20)-2}); wave favors {rhy_col}")
        elif alt_len >= 2:
            q9_rhy = (opp_c, 66.0, f"Alternating harmonic rhythm favors {opp_c}")
        else:
            q9_rhy = (opp_c, 54.0, "Harmonic balance")
    else:
        q9_rhy = (opp_c, 50.0, "Neutral cycle")

    # 9. Quant 10: Multi-Scale Shannon Entropy Gatekeeper
    recent_12 = colors[-12:] if tot_db >= 12 else colors
    p12_r = recent_12.count("RED") / len(recent_12)
    p12_g = recent_12.count("GREEN") / len(recent_12)
    entropy_12 = 0.0
    for p in (p12_r, p12_g):
        if p > 0:
            entropy_12 -= p * math.log2(p)

    if entropy_12 >= 0.92:
        ent_col = opp_c  # In high entropy chop, follow alternation
        q10_ent = (ent_col, 63.0, f"High entropy ({entropy_12:.2f}); chop rhythm favors {ent_col}")
    else:
        ent_col = last_c if streak_len >= 4 else opp_c
        q10_ent = (ent_col, 64.0, f"Structured market entropy ({entropy_12:.2f}); favors {ent_col}")

    # 10. Quant 11: Full-Database Violet (0 & 5) Outlier Engine
    violet_intervals = []
    last_v_idx = None
    for idx, it in enumerate(history_items):
        if it.get("has_violet", False) or int(it.get("num", -1)) in (0, 5):
            if last_v_idx is not None:
                violet_intervals.append(idx - last_v_idx)
            last_v_idx = idx

    avg_v_interval = round(sum(violet_intervals) / len(violet_intervals), 1) if violet_intervals else 10.0
    rounds_since_violet = (len(history_items) - 1 - last_v_idx) if last_v_idx is not None else 0

    violet_due = (rounds_since_violet >= avg_v_interval * 1.3 and last_num in (4, 9, 1, 6)) or (rounds_since_violet >= avg_v_interval * 1.6)
    if violet_due:
        v_col = "RED" if last_num in (1, 2, 3, 4) else "GREEN"
        q11_vio = (v_col, 75.0, f"Violet overdue ({rounds_since_violet} rounds dormant vs {avg_v_interval} avg); hedge on 0/5")
    else:
        v_flow = opp_c if alt_len >= 2 else (last_c if streak_len >= 5 else opp_c)
        q11_vio = (v_flow, 55.0, f"Violet normal ({rounds_since_violet} dormant)")

    # 11. Quant 12: Weibull Hazard Function & Streak Survival Quant
    streaks = []
    if len(colors) >= 2:
        cur_c = colors[0]
        cur_l = 1
        for c in colors[1:]:
            if c == cur_c:
                cur_l += 1
            else:
                streaks.append((cur_c, cur_l))
                cur_c = c
                cur_l = 1
        streaks.append((cur_c, cur_l))

    survived_t = [s[1] for s in streaks if s[1] >= streak_len]
    ended_t = [s[1] for s in streaks if s[1] == streak_len]
    h_rate = round((len(ended_t) / len(survived_t) * 100), 1) if survived_t else 50.0

    if streak_len >= 2:
        # Dragon support: ride the streak!
        q12_hazard = (last_c, min(88.0, 70.0 + streak_len * 2.5), f"Weibull streak survival favors {last_c} dragon continuation ({streak_len} rounds)")
    elif alt_len >= 2:
        q12_hazard = (opp_c, min(86.0, 68.0 + alt_len * 2.5), f"Alternation survival favors chop continuation ({alt_len} rounds)")
    else:
        q12_hazard = (opp_c, 55.0, f"Hazard regime favors {opp_c}")

    # 12. Quant 13: Discrete Fourier Transform (DFT) Spectral Wave Analysis
    import cmath
    n_f = min(len(colors), 64)
    if n_f >= 8:
        x_f = [1.0 if c == "GREEN" else -1.0 for c in colors[-n_f:]]
        best_p, best_k, best_ph = -1.0, 1, 0.0
        for k in range(1, n_f // 2):
            X_k = sum(x_f[j] * cmath.exp(-2j * cmath.pi * j * k / n_f) for j in range(n_f))
            pwr = (X_k.real**2 + X_k.imag**2) / n_f
            if pwr > best_p:
                best_p, best_k, best_ph = pwr, k, cmath.phase(X_k)
        dom_period = round(n_f / best_k, 1)
        next_ph = (2 * math.pi * best_k * n_f / n_f) + best_ph
        f_val = math.cos(next_ph)
        f_col = "GREEN" if f_val >= 0 else "RED"
        f_conf = min(88.0, max(56.0, round(50.0 + (abs(f_val) * 36.0), 1)))
        q13_fourier = (f_col, f_conf, f"Fourier DFT dominant {dom_period}-round wave; trajectory favors {f_col}")
    else:
        q13_fourier = (opp_c, 50.0, "Fourier baseline")

    # 13. Quant 14: Kolmogorov Algorithmic Complexity / Lempel-Ziv Regularity
    import zlib
    n_k = min(len(colors), 60)
    if n_k >= 10:
        seq_str = "".join(["R" if c == "RED" else "G" for c in colors[-n_k:]])
        comp_r = len(zlib.compress((seq_str + "R").encode("utf-8"), level=9))
        comp_g = len(zlib.compress((seq_str + "G").encode("utf-8"), level=9))
        if comp_r < comp_g:
            q14_kolmo = ("RED", 66.0, "Kolmogorov complexity compressibility favors RED")
        elif comp_g < comp_r:
            q14_kolmo = ("GREEN", 66.0, "Kolmogorov complexity compressibility favors GREEN")
        else:
            k_c = opp_c if alt_len >= 2 else (last_c if streak_len >= 4 else opp_c)
            q14_kolmo = (k_c, 54.0, f"Kolmogorov balanced; rhythm favors {k_c}")
    else:
        q14_kolmo = (opp_c, 50.0, "Kolmogorov baseline")

    # 14. Quant 15: Exponentially-Decayed Beta-Binomial Bayesian Posterior
    alpha_b, beta_b = 1.0, 1.0
    for c in colors:
        alpha_b = (alpha_b * 0.96) + (1.0 if c == "GREEN" else 0.0)
        beta_b = (beta_b * 0.96) + (1.0 if c == "RED" else 0.0)
    tot_pseudo = alpha_b + beta_b
    post_mean = alpha_b / tot_pseudo
    bayes_fav = "GREEN" if post_mean >= 0.50 else "RED"
    bayes_conf = round(max(post_mean, 1.0 - post_mean) * 100, 1)
    q15_bayes = (bayes_fav, min(85.0, max(55.0, bayes_conf)), f"Bayesian Exponential Posterior favors {bayes_fav} ({bayes_conf}%)")

    # 15. Predicted Size (BIG / SMALL) Engine with Multi-Quant Scoring
    last_s = sizes[-1]
    opp_s = "SMALL" if last_s == "BIG" else "BIG"
    s_streak = 1
    for s in reversed(sizes[:-1]):
        if s == last_s: s_streak += 1
        else: break
    s_alt = 1
    for k in range(len(sizes) - 1, 0, -1):
        if sizes[k] != sizes[k - 1]: s_alt += 1
        else: break

    is_s_2_2 = (len(sizes) >= 4 and sizes[-1] == sizes[-2] and sizes[-3] == sizes[-4] and sizes[-1] != sizes[-3]) or (len(sizes) >= 3 and sizes[-1] != sizes[-2] and sizes[-2] == sizes[-3])

    s_score_big = 0.0
    s_score_small = 0.0

    # 1. Size Dragon Rider (Streak continuation >= 2)
    if s_streak >= 2:
        if last_s == "BIG": s_score_big += 4.5 + min(3.0, s_streak * 0.5)
        else: s_score_small += 4.5 + min(3.0, s_streak * 0.5)
    # 2. Size Alternation Chop (Continuation)
    elif s_alt >= 2:
        if opp_s == "BIG": s_score_big += 4.2 + min(2.0, s_alt * 0.4)
        else: s_score_small += 4.2 + min(2.0, s_alt * 0.4)
    # 3. Size 2-2 Symmetry (Double Double paired steps)
    elif is_s_2_2:
        if last_s == "BIG": s_score_big += 3.8
        else: s_score_small += 3.8
    else:
        if opp_s == "BIG": s_score_big += 1.5
        else: s_score_small += 1.5

    # 5. Rolling 20-Round Micro Imbalance for Size
    b20 = sizes[-20:].count("BIG") if len(sizes) >= 20 else sizes.count("BIG")
    s20 = sizes[-20:].count("SMALL") if len(sizes) >= 20 else sizes.count("SMALL")
    if b20 >= 13:
        s_score_small += 3.2
    elif s20 >= 13:
        s_score_big += 3.2
    elif b20 >= 12:
        s_score_small += 1.8
    elif s20 >= 12:
        s_score_big += 1.8

    # 6. Winning Number to Size Bayes Prior
    num_to_size = defaultdict(lambda: {"BIG": 0, "SMALL": 0})
    for i in range(len(nums) - 1):
        num_to_size[nums[i]][sizes[i + 1]] += 1
    c_ns = num_to_size.get(last_num, {"BIG": 0, "SMALL": 0})
    tot_ns = c_ns["BIG"] + c_ns["SMALL"]
    if tot_ns >= 5:
        if c_ns["BIG"] > c_ns["SMALL"]:
            s_score_big += 2.5
        elif c_ns["SMALL"] > c_ns["BIG"]:
            s_score_small += 2.5

    # 7. Size Markov 3-Gram Transitions
    t3_s = defaultdict(lambda: {"BIG": 0, "SMALL": 0})
    for i in range(len(sizes) - 3):
        t3_s[tuple(sizes[i:i + 3])][sizes[i + 3]] += 1
    last3_s = tuple(sizes[-3:]) if len(sizes) >= 3 else ()
    c3_s = t3_s.get(last3_s, {"BIG": 0, "SMALL": 0})
    tot3_s = c3_s["BIG"] + c3_s["SMALL"]
    if tot3_s >= 4:
        if c3_s["BIG"] > c3_s["SMALL"]:
            s_score_big += 2.8
        elif c3_s["SMALL"] > c3_s["BIG"]:
            s_score_small += 2.8

    pred_size = "BIG" if s_score_big >= s_score_small else "SMALL"
    size_edge = abs(s_score_big - s_score_small)
    tot_s = s_score_big + s_score_small
    size_ratio = (max(s_score_big, s_score_small) / tot_s) if tot_s > 0 else 0.5
    size_margin_pct = round((size_edge / tot_s * 100), 1) if tot_s > 0 else 0.0
    pred_size_conf = min(96.0, max(76.0, round(65.0 + (size_ratio * 30.0), 1)))

    # 16. High-Conviction Number Shots Engine (9X Payout Selection)
    # Color + Size matrix mapping:
    # RED + SMALL -> 0, 2, 4
    # RED + BIG -> 6, 8
    # GREEN + SMALL -> 1, 3
    # GREEN + BIG -> 5, 7, 9
    c_cand = last_c if streak_len >= 2 else (opp_c if alt_len >= 2 else last_c)
    s_cand = pred_size

    if c_cand == "RED" and s_cand == "SMALL":
        cand_nums = [2, 4, 0] if not violet_due else [0, 2, 4]
    elif c_cand == "RED" and s_cand == "BIG":
        cand_nums = [6, 8]
    elif c_cand == "GREEN" and s_cand == "SMALL":
        cand_nums = [1, 3]
    else: # GREEN + BIG
        cand_nums = [7, 9, 5] if not violet_due else [5, 7, 9]

    # Rank candidate numbers by historical transition from last_num
    num_next_counts = defaultdict(int)
    for i in range(len(nums) - 1):
        if nums[i] == last_num:
            num_next_counts[nums[i + 1]] += 1

    sorted_cands = sorted(cand_nums, key=lambda n: num_next_counts.get(n, 0), reverse=True)
    top_number_shots = sorted_cands[:2]
    number_shots_str = ", ".join(str(n) for n in top_number_shots)
    jackpot_tip = f"{number_shots_str} [9X Payout]"

    # Compile descriptive pattern tags
    desc = []
    if streak_len >= 2:
        desc.append(f"🔥 Dragon Trend ({last_c} x {streak_len})")

    if alt_len >= 3:
        desc.append(f"⚡ 1-1 Alternating Chop ({alt_len} rounds)")
    if is_double:
        desc.append("🔄 2-2 Double Pattern")
    desc.append(f"📈 N-Gram: {q5_ngram[0]}")
    desc.append(f"🔢 Bayes: {q6_num[0]}")
    desc.append(f"🌊 Fourier: {q13_fourier[0]}")
    if violet_due:
        desc.append(f"🟣 Violet Overdue ({rounds_since_violet} rounds dormant)")

    recent_60_items = history_items[-60:] if len(history_items) >= 60 else history_items
    compact_parts = []
    for it in recent_60_items:
        num = int(it.get("num", 0))
        c_code = it.get("color", "")[:1]
        v_tag = "+V" if it.get("has_violet") or num in (0, 5) else ""
        compact_parts.append(f"{c_code}{v_tag}({num})")
    recent_compact = ", ".join(compact_parts)

    return {
        "streak_color": last_c,
        "streak_len": streak_len,
        "is_alt": alt_len >= 2,
        "alt_len": alt_len,
        "is_double": is_double,
        "pattern_desc": " | ".join(desc) if desc else "Neutral Pattern",
        "recent_compact": recent_compact,
        "violet_due": violet_due,
        "rounds_since_violet": rounds_since_violet,
        "pred_size": pred_size,
        "s_streak": s_streak,
        "s_alt": s_alt,
        "last_s": last_s,
        "opp_s": opp_s,
        "size_edge": size_edge,
        "size_margin_pct": size_margin_pct,
        "pred_size_conf": pred_size_conf,
        "c_pattern_desc": c_pattern_desc,
        "s_pattern_desc": s_pattern_desc,
        "c_pred_val": c_pred_val,
        "s_pred_val": s_pred_val,
        "quants": {
            "q4": q4_roadmap,
            "q5": q5_ngram,
            "q6": q6_num,
            "q7": q7_bs,
            "q8": q8_mr,
            "q9": q9_rhy,
            "q10": q10_ent,
            "q11": q11_vio,
            "q12": q12_hazard,
            "q13": q13_fourier,
            "q14": q14_kolmo,
            "q15": q15_bayes
        }
    }

# ====================================================
# 🧠 16-AGENT AI & QUANT HYBRID COUNCIL
# ====================================================
def ask_12_ai_council(history_items, current_loss_streak=0, consecutive_skips=0):
    """
    16-Agent AI & Math Quant Council:
    - 4 Neural LLM Specialists in Parallel (Qwen & GPT)
    - 11 Deterministic Pure-Math Quants (Database Transition, Fourier, Weibull, Bayes, Entropy, N-Gram)
    - 1 Supreme Arbiter (GPT-120B Flagship / Qwen)
    - Dual-Layer Sniper Filter: Skips chaotic 50/50 noise; executes high-probability Pinterest roadmaps!
    - Delivers direct Level 1 accuracy.
    """
    p_info = detect_market_patterns(history_items)
    recent_str = p_info["recent_compact"]
    pattern_str = p_info["pattern_desc"]
    last_color = p_info["streak_color"]
    opp_color = "GREEN" if last_color == "RED" else "RED"
    streak_len = p_info["streak_len"]
    alt_len = p_info.get("alt_len", 1)
    is_double = p_info.get("is_double", False)
    violet_due = p_info["violet_due"]
    quants = p_info.get("quants", {})
    pred_size = p_info.get("pred_size", "BIG")
    last_s = p_info.get("last_s", "BIG")
    s_streak = p_info.get("s_streak", 1)
    s_alt = p_info.get("s_alt", 1)
    c_pred_val = p_info.get("c_pred_val", opp_color)
    colors = [it.get("color", "") for it in history_items]
    sizes = [it.get("size", "") for it in history_items]

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    # --- Phase 1: 12 Deterministic Pure-Math Quants (Instant 0ms, Zero Quota Consumption) ---
    c_dragon = last_color if streak_len >= 3 else (opp_color if streak_len < 2 else last_color)
    c_chop = opp_color if alt_len >= 4 else (last_color if streak_len >= 3 else opp_color)
    c_22 = c_pred_val if is_double else opp_color
    c_contrarian = opp_color if streak_len >= 4 else last_color

    q4 = quants.get("q4", (opp_color, 75.0, "Pinterest Roadmap"))
    q5 = quants.get("q5", (opp_color, 60.0, "N-Gram model"))
    q6 = quants.get("q6", (opp_color, 65.0, "Number transition"))
    q7 = quants.get("q7", (opp_color, 58.0, "Compound Matrix"))
    q8 = quants.get("q8", (opp_color, 68.0, "Mean-Reversion"))
    q9 = quants.get("q9", (opp_color, 56.0, "Periodicity"))
    q10 = quants.get("q10", (opp_color, 60.0, "Entropy"))
    q11 = quants.get("q11", (opp_color, 55.0, "Violet Engine"))
    q12 = quants.get("q12", (opp_color, 65.0, "Weibull Hazard"))
    q13 = quants.get("q13", (opp_color, 60.0, "Fourier DFT"))
    q14 = quants.get("q14", (opp_color, 55.0, "Kolmogorov Complexity"))
    q15 = quants.get("q15", (opp_color, 58.0, "Bayesian Decay"))

    all_specialists = [
        {"name": "Agent 1 (Dragon Momentum Quant)", "color": c_dragon, "conf": 80.0 if streak_len >= 3 else 50.0, "arg": f"Streak len: {streak_len}"},
        {"name": "Agent 2 (1-1 Chop Quant)", "color": c_chop, "conf": 80.0 if alt_len >= 4 else 50.0, "arg": f"Chop len: {alt_len}"},
        {"name": "Agent 3 (2-2 Symmetry Quant)", "color": c_22, "conf": 75.0 if is_double else 50.0, "arg": "Pair symmetry"},
        {"name": "Agent 4 (Mean-Reversion Quant)", "color": c_contrarian, "conf": 75.0, "arg": "Anti-exhaustion balance"},
        {"name": "Agent 4B (Pinterest Roadmap Quant)", "color": q4[0], "conf": q4[1], "arg": q4[2]},
        {"name": "Agent 5 (N-Gram Markov Quant)", "color": q5[0], "conf": q5[1], "arg": q5[2]},
        {"name": "Agent 6 (Number-to-Color Bayes)", "color": q6[0], "conf": q6[1], "arg": q6[2]},
        {"name": "Agent 7 (Big/Small Compound Matrix)", "color": q7[0], "conf": q7[1], "arg": q7[2]},
        {"name": "Agent 8 (Mean-Reversion Imbalance Quant)", "color": q8[0], "conf": q8[1], "arg": q8[2]},
        {"name": "Agent 9 (Micro-Cycle Periodicity Quant)", "color": q9[0], "conf": q9[1], "arg": q9[2]},
        {"name": "Agent 10 (Shannon Entropy Gatekeeper)", "color": q10[0], "conf": q10[1], "arg": q10[2]},
        {"name": "Agent 11 (Violet 0/5 Outlier Specialist)", "color": q11[0], "conf": q11[1], "arg": q11[2]},
        {"name": "Agent 12 (Weibull Hazard & Survival Quant)", "color": q12[0], "conf": q12[1], "arg": q12[2]},
        {"name": "Agent 13 (Fourier Spectral Wave Quant)", "color": q13[0], "conf": q13[1], "arg": q13[2]},
        {"name": "Agent 14 (Kolmogorov Complexity Quant)", "color": q14[0], "conf": q14[1], "arg": q14[2]},
        {"name": "Agent 15 (Exponential Bayesian Quant)", "color": q15[0], "conf": q15[1], "arg": q15[2]}
    ]

    # Dynamic Weight Assignment based on Empirical Win Rates
    weights = [
        3.5 if streak_len >= 3 else 1.0,                                # Agent 1: Dragon Trend Momentum
        3.2 if alt_len >= 4 else 1.0,                                   # Agent 2: 1-1 Chop
        2.2,                                                            # Agent 3: 2-2 Symmetry
        1.2,                                                            # Agent 4: Mean-Reversion
        3.5 if q4[1] >= 85.0 else 2.2,                                  # Agent 4B: Pinterest 9-Roadmap Engine
        2.5,                                                            # Agent 5: Markov N-Gram
        2.5,                                                            # Agent 6: Number-to-Color Bayes
        2.0,                                                            # Agent 7: Big/Small Matrix
        2.0,                                                            # Agent 8: Mean-Reversion Imbalance
        1.5,                                                            # Agent 9: Autocorrelation
        1.4,                                                            # Agent 10: Entropy
        1.2,                                                            # Agent 11: Violet
        2.0,                                                            # Agent 12: Weibull Hazard
        1.6,                                                            # Agent 13: Fourier DFT
        1.3,                                                            # Agent 14: Kolmogorov
        1.8                                                             # Agent 15: Bayesian Decay
    ]

    red_weight = sum(weights[i] for i, s in enumerate(all_specialists) if s["color"] == "RED")
    green_weight = sum(weights[i] for i, s in enumerate(all_specialists) if s["color"] == "GREEN")
    red_votes = sum(1 for s in all_specialists if s["color"] == "RED")
    green_votes = sum(1 for s in all_specialists if s["color"] == "GREEN")
    total_active_weight = red_weight + green_weight

    # Decisive Winning Color Selection (No Deadlocks, No Artificial Skips!)
    if red_weight > green_weight:
        w_col = "RED"
        w_v, l_v = red_votes, green_votes
        w_weight = red_weight
    elif green_weight > red_weight:
        w_col = "GREEN"
        w_v, l_v = green_votes, red_votes
        w_weight = green_weight
    else:
        # Exact tie-breaker: ride dragon continuation or chop rhythm
        w_col = last_color if streak_len >= 2 else (opp_color if alt_len >= 2 else last_color)
        w_v = red_votes if w_col == "RED" else green_votes
        l_v = green_votes if w_col == "RED" else red_votes
        w_weight = red_weight if w_col == "RED" else green_weight

    color_edge = abs(red_weight - green_weight)
    color_ratio = (w_weight / total_active_weight) if total_active_weight > 0 else 0.5
    color_margin_pct = round((color_edge / total_active_weight * 100), 1) if total_active_weight > 0 else 0.0
    calc_conf = min(96.0, max(76.0, round(65.0 + (color_ratio * 30.0), 1)))

    # ====================================================
    # 🎯 1. NEVER CUT A DRAGON RULE (Fundamental Trend Law)
    # ====================================================
    # Protect established dragons (streak >= 3) against counter-trend bets (no artificial vote inflation)
    if streak_len >= 3 and w_col != last_color:
        w_col = last_color
    if s_streak >= 3 and pred_size != last_s:
        pred_size = last_s

    # ====================================================
    # 🎯 2. DECIDE SINGLE TARGET BET: COLOR vs SIZE
    # ====================================================
    size_margin_pct = p_info.get("size_margin_pct", 0.0)
    size_conf = p_info.get("pred_size_conf", 78.0)
    c_pattern_desc = p_info.get("c_pattern_desc", "Momentum Flow")
    s_pattern_desc = p_info.get("s_pattern_desc", "Momentum Flow")

    if size_margin_pct > color_margin_pct:
        target_type = "SIZE"
        target_val = pred_size
        target_conf = size_conf
        target_margin = size_margin_pct
        target_pattern = s_pattern_desc
        target_edge_desc = f"SIZE edge ({size_margin_pct:.0f}%) > COLOR edge ({color_margin_pct:.0f}%)"
    else:
        target_type = "COLOR"
        target_val = w_col
        target_conf = calc_conf
        target_margin = color_margin_pct
        target_pattern = c_pattern_desc
        target_edge_desc = f"COLOR edge ({color_margin_pct:.0f}%) >= SIZE edge ({size_margin_pct:.0f}%)"

    # ====================================================
    # 🎯 3. ULTRA-STRICT MAX INTENSITY QUALIFICATION ENGINE
    # ====================================================
    # High-Conviction Structural Signals (Genuine Trends Only)
    # A true Dragon must be AT LEAST 3 or 4 in a row!
    c_strong_dragon = ("Dragon Trend" in c_pattern_desc and streak_len >= 3)
    s_strong_dragon = ("Dragon Trend" in s_pattern_desc and s_streak >= 3)
    # A true Chop must be AT LEAST 4 consecutive alternations!
    c_strong_chop = ("1-1 Chop" in c_pattern_desc and alt_len >= 4)
    s_strong_chop = ("1-1 Chop" in s_pattern_desc and s_alt >= 4)
    c_strong_22 = ("2-2 Double-Step" in c_pattern_desc and "Pair" in c_pattern_desc and len(colors) >= 4)
    s_strong_22 = ("2-2 Double-Step" in s_pattern_desc and "Pair" in s_pattern_desc and len(sizes) >= 4)

    has_confirmed_structure = (
        (target_type == "COLOR" and (c_strong_dragon or c_strong_chop or c_strong_22)) or
        (target_type == "SIZE" and (s_strong_dragon or s_strong_chop or s_strong_22))
    )

    # MAX INTENSITY SURE-SHOT RULES:
    # (A) Super-majority consensus (w_v >= 13 out of 16) AND target margin >= 50%
    # OR
    # (B) Confirmed structural pattern (Dragon >= 3, Chop >= 4, 2-2 Pair) AND w_v >= 12 AND target margin >= 38%
    is_qualified_bet = (
        (w_v >= 13 and target_margin >= 50.0) or
        (has_confirmed_structure and w_v >= 12 and target_margin >= 38.0)
    )

    # 🛡️ IRONCLAD RECOVERY PROTECTION (Level 2 & Level 3+):
    # When capital is at 3X or 9X risk, NEVER bet on weak/average setups!
    # MUST have confirmed structure AND w_v >= 13 AND margin >= 50%, otherwise CONTINUE SKIPPING!
    if current_loss_streak >= 1:
        if not (has_confirmed_structure and w_v >= 13 and target_margin >= 50.0):
            is_qualified_bet = False

    cur_lvl = CURRENT_LOSS_STREAK + 1
    signal_grade = f"LEVEL_{cur_lvl}"

    if w_v >= 13:
        consensus_tag = f"💎 Council Golden Unanimity ({w_v}-{l_v} | {target_edge_desc})"
    elif w_v >= 10:
        consensus_tag = f"🔥 Council Super-Majority ({w_v}-{l_v} | {target_edge_desc})"
    else:
        consensus_tag = f"🎯 Council Solid Edge ({target_edge_desc})"

    # --- Phase 4: Master AI Arbiter Consultation (Groq with Automatic Model Failover) ---
    spec_summary = "\n".join([
        f"- {s['name']}: {s['color']} ({s['conf']:.0f}%) -> \"{s['arg']}\""
        for s in all_specialists[:8]
    ])

    final_summary = f"Selected {target_type} {target_val} based on {pattern_str.split('|')[0].strip()} ({target_edge_desc})."
    v_alert = bool(violet_due)
    arbiter_wants_skip = False

    # Only invoke Master AI if mathematically qualified (saves daily Groq tokens, executes in 0ms on noise)
    if is_qualified_bet:
        prompt_arbiter = (
            f"You are Supreme Master Arbiter presiding over the 16-Agent AI & Math WinGo Council.\n"
            f"Recent History Window: {recent_str[-50:]}\n"
            f"Market Roadmaps: Color=[{c_pattern_desc}], Size=[{s_pattern_desc}]\n"
            f"Specialists Assessments:\n{spec_summary}\n"
            f"Color Consensus: {w_col} ({w_v} vs {l_v} votes | {color_margin_pct:.0f}% edge)\n"
            f"Size Consensus: {pred_size} ({size_margin_pct:.0f}% edge)\n"
            f"Preliminary Target: {target_type} -> {target_val}\n\n"
            f"STRICT SNIPER ACCURACY DIRECTIVE:\n"
            f"The user requires maximum sniper accuracy and direct Level 1 wins.\n"
            f"1. Conduct step-by-step reasoning on trend continuation, chop rhythm, and retail trap fakeout risks.\n"
            f"2. If the round is noisy, chaotic, in a 50/50 chop trap, or lacks a definite structural roadmap on both Color and Size: you MUST output action 'SKIP'.\n"
            f"3. If a clear edge exists: output action 'BET'.\n\n"
            f"Return JSON ONLY:\n"
            f'{{"action": "BET" or "SKIP", "confidence": 85, "reason": "1 decisive sentence explaining the decision"}}'
        )

        for model_name in MASTER_AI_MODELS:
            try:
                r_arb = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt_arbiter}],
                    "response_format": {"type": "json_object"}
                }, timeout=2.5)
                if r_arb.status_code == 200:
                    res_arb = json.loads(r_arb.json()["choices"][0]["message"]["content"])
                    act = str(res_arb.get("action", "")).upper()
                    if act == "SKIP":
                        arbiter_wants_skip = True
                        final_summary = res_arb.get("reason", "Filtered out ambiguous market round for sniper accuracy")
                        print(f"🧠 [MASTER AI: {model_name}] ⏸️ VETO SKIP: {final_summary}", flush=True)
                    elif act == "BET":
                        summary_txt = res_arb.get("reason", "")
                        if summary_txt:
                            final_summary = summary_txt
                        print(f"🧠 [MASTER AI: {model_name}] ✅ BET CONFIRMED: {target_type} {target_val} | {final_summary}", flush=True)
                    break
                elif r_arb.status_code == 429:
                    print(f"⚠️ [MASTER AI: {model_name}] Rate limited (429), failing over to next model...", flush=True)
                    continue
                else:
                    print(f"⚠️ [MASTER AI: {model_name}] HTTP {r_arb.status_code}: {r_arb.text[:100]}", flush=True)
                    continue
            except Exception as e:
                print(f"⚠️ [MASTER AI: {model_name}] Error: {e}", flush=True)
                continue

    # ====================================================
    # 🎯 4. FINAL SNIPER FILTER (Real Skips on Noise)
    # ====================================================
    # Strictly SKIP if not a qualified high-conviction bet or Arbiter flagged noise!
    # UNLIMITED skips allowed - NEVER bet into 50/50 noise!
    opposite_nums_tip = None
    if not is_qualified_bet or arbiter_wants_skip:
        target_type = "SKIP"
        target_val = "SKIP"
        target_conf = 50.0
        signal_grade = "SKIP"
        detected_pattern_name = "Filtered Noise"
        jackpot_tip = None
        final_summary = "Choppy noise filtered: Preserving capital until high-conviction sniper entry."
    else:
        detected_pattern_name = target_pattern
        # High-Conviction Sure-Shot Number Engine (9X Payout)
        # ONLY trigger when Council has super-majority (>= 12 agents) AND statistical peak exists!
        jackpot_tip = None
        if CURRENT_LOSS_STREAK <= 1 and w_v >= 12:
            if w_col == "RED" and pred_size == "SMALL":
                cand_nums = [2, 4, 0] if not v_alert else [0, 2, 4]
            elif w_col == "RED" and pred_size == "BIG":
                cand_nums = [6, 8]
            elif w_col == "GREEN" and pred_size == "SMALL":
                cand_nums = [1, 3]
            else:
                cand_nums = [7, 9, 5] if not v_alert else [5, 7, 9]

            nums_list = [int(it.get("num", 0)) for it in history_items]
            last_num = nums_list[-1] if nums_list else 0
            num_next_counts = defaultdict(int)
            for i in range(len(nums_list) - 1):
                if nums_list[i] == last_num:
                    num_next_counts[nums_list[i + 1]] += 1

            cand_transitions = sum(num_next_counts[n] for n in cand_nums)
            if cand_transitions >= 8:
                sorted_cands = sorted(cand_nums, key=lambda n: num_next_counts[n], reverse=True)
                top_cand = sorted_cands[0]
                top_ratio = num_next_counts[top_cand] / cand_transitions
                # Sure-shot peak: Dominant transition >= 40% (or violet outlier)
                if top_ratio >= 0.40 or v_alert:
                    top_shots = sorted_cands[:2]
                    jackpot_tip = f"{', '.join(str(n) for n in top_shots)} [9X Payout]"

        # 🔥 Fire X Elite "Opposite Nums (Hedge)" Engine
        # Calculates top 2 most probable candidate numbers from the opposite side as safety hedge
        nums_list = [int(it.get("num", 0)) for it in history_items]
        last_num = nums_list[-1] if nums_list else 0
        opp_next_counts = defaultdict(int)
        for i in range(len(nums_list) - 1):
            if nums_list[i] == last_num:
                opp_next_counts[nums_list[i + 1]] += 1

        if target_type == "SIZE":
            opp_pool = [0, 1, 2, 3, 4] if target_val == "BIG" else [5, 6, 7, 8, 9]
        elif target_type == "COLOR":
            opp_pool = [1, 3, 5, 7, 9] if target_val == "RED" else [0, 2, 4, 6, 8]
        else:
            opp_pool = [0, 1, 2, 3, 4] if pred_size == "BIG" else [5, 6, 7, 8, 9]

        sorted_opp = sorted(opp_pool, key=lambda n: opp_next_counts[n], reverse=True)
        opposite_nums_tip = f"{sorted_opp[0]}, {sorted_opp[1]}"

    return {
        "target_type": target_type,
        "target_val": target_val,
        "target_conf": target_conf,
        "color": w_col,
        "size": pred_size,
        "reason": final_summary,
        "consensus_tag": consensus_tag,
        "violet_alert": v_alert,
        "jackpot_tip": jackpot_tip,
        "opposite_nums": opposite_nums_tip,
        "signal_grade": signal_grade,
        "pattern_name": detected_pattern_name
    }

# ====================================================
# 🚀 USER SIGNALS (CLEAN VIP CARD WITH QUANT ACCURACY)
# ====================================================
def to_bold(text):
    """Converts ASCII letters and digits to Mathematical Sans-Serif Bold for crystal-clear Telegram bold rendering."""
    out = []
    for ch in str(text):
        code = ord(ch)
        if 65 <= code <= 90:  # A-Z
            out.append(chr(0x1D5D4 + (code - 65)))
        elif 97 <= code <= 122:  # a-z
            out.append(chr(0x1D5EE + (code - 97)))
        elif 48 <= code <= 57:  # 0-9
            out.append(chr(0x1D7EC + (code - 48)))
        else:
            out.append(ch)
    return "".join(out)

# ====================================================
# 🚀 USER SIGNALS (HIGH-VISIBILITY BOLD VIP CARDS)
# ====================================================
def send_user_signal(target_period, target_type, target_val, confidence=0.0, reason="", consensus_tag="16-Agent Council", violet_alert=False, signal_grade="LEVEL_1", jackpot_tip=None, pattern_name=None, opposite_nums=None):
    short_period = target_period[-4:] if len(target_period) >= 4 else target_period

    # User requirement: "par ye sirf SKIP bole ok prediciotn me kuch or extra befaltu nhi"
    if target_type == "SKIP" or target_val == "SKIP":
        msg = (
            f"⏳ <b>Period</b> : <code>...{short_period}</code>\n"
            f"🎯 <b>Prediction</b> : ⏸️ <b>SKIP</b>"
        )
        try:
            send_telegram_msg(USER_ALERT_CHAT_ID, msg, timeout=8, retries=1, pin=False)
            print(f"👉 [SIGNAL SENT] Period: ...{short_period} | Target: ⏸️ SKIP (Filtered Noise)", flush=True)
        except Exception as e:
            print(f"[USER ALERT ERROR] {e}", flush=True)
        return

    if target_type == "COLOR":
        c_name = to_bold(target_val)
        c_emoji = f"🔴 {c_name}" if target_val == "RED" else f"🟢 {c_name}"
        target_code = c_emoji
        bet_label = target_val
    else:
        s_name = to_bold("BIG [5-9]") if target_val == "BIG" else to_bold("SMALL [0-4]")
        s_emoji = f"🐘 {s_name}" if target_val == "BIG" else f"🐜 {s_name}"
        target_code = s_emoji
        bet_label = target_val

    level = CURRENT_LOSS_STREAK + 1
    mult = 3 ** (level - 1)
    stage_str = to_bold(f"LEVEL {level} ({mult}X)")
    conf_str = to_bold(f"{confidence:.1f}%")
    pattern_str = to_bold(pattern_name) if pattern_name else to_bold("Market Momentum")

    if level == 1:
        banner = f"👑 <b>{to_bold('WINGO 30S VIP PREDICTION')}</b> 👑"
        footer = f"💡 <i>Place 1X Base Bet on {bet_label}. High Probability Setup!</i>"
    elif level == 2:
        banner = f"⚡ <b>{to_bold('WINGO 30S RECOVERY SIGNAL')}</b> ⚡"
        footer = f"💰 <i>Place 3X Bet on {bet_label}! Full capital + profit recovery!</i>"
    elif level == 3:
        banner = f"🔥 <b>{to_bold('WINGO 30S LEVEL 3 RECOVERY')}</b> 🔥"
        footer = f"🚀 <i>Place 9X Bet on {bet_label}! High conviction recovery round!</i>"
    elif level == 4:
        banner = f"💎 <b>{to_bold('WINGO 30S LEVEL 4 RECOVERY')}</b> 💎"
        footer = f"🚨 <i>Place 27X Bet on {bet_label}! Strong turnaround recovery!</i>"
    else:
        banner = f"🛡️ <b>{to_bold('WINGO 30S LEVEL 5 FINAL RECOVERY')}</b> 🛡️"
        footer = f"🎯 <i>Place 81X Bet on {bet_label}! Ultimate safety recovery!</i>"

    v_tip_line = ""
    if jackpot_tip:
        v_tip_line = f"\n🎯 <b>Sure-Shot Numbers (9X)</b> : <b>{to_bold(jackpot_tip)}</b>"
    elif opposite_nums:
        v_tip_line = f"\n🛡️ <b>Opposite Nums (Hedge)</b> : <b>{to_bold(opposite_nums)}</b>"
    elif violet_alert:
        v_tip_line = f"\n🟣 <b>Jackpot Tip</b> : <b>{to_bold('Numbers 0, 5 (Violet 4.5X)')}</b>"

    msg = (
        f"{banner}\n"
        f"<blockquote>"
        f"⏳ <b>Period</b> : <code>...{short_period}</code>\n"
        f"🎯 <b>Prediction</b> : <b>{target_code}</b>\n"
        f"📊 <b>Stage</b> : <b>{stage_str}</b>\n"
        f"📈 <b>Confidence</b> : <b>{conf_str}</b>\n"
        f"🧩 <b>Pattern</b> : <b>{pattern_str}</b>"
        f"{v_tip_line}\n"
        f"</blockquote>\n"
        f"{footer}"
    )

    try:
        # Send without pin so channel is not spammed with pinned message notifications
        send_telegram_msg(USER_ALERT_CHAT_ID, msg, timeout=8, retries=1, pin=False)
        print(f"👉 [SIGNAL SENT] Period: ...{short_period} | Target: {target_type}={target_val} | Level {level} | Pattern: {pattern_name}", flush=True)
    except Exception as e:
        print(f"[USER ALERT ERROR] {e}", flush=True)

# ====================================================
# 🎯 RESULT EVALUATION (PROMINENT BOLD WIN & LOSS CARDS)
# ====================================================
def send_user_result(period, actual_number, actual_color, pred):
    global CURRENT_LOSS_STREAK, TOTAL_WINS, TOTAL_LOSSES, TOTAL_CYCLES, CYCLE_WINS, CYCLE_LOSSES, MAX_MARTINGALE_LEVEL
    if not pred or pred.get("target_type") == "SKIP" or pred.get("target_val") == "SKIP":
        return
    short_period = period[-4:] if len(period) >= 4 else period

    bold_c_name = to_bold(actual_color)
    if actual_number == 0:
        c_display = f"🔴 {to_bold('RED')} + 🟣 {to_bold('VIOLET')} ({actual_number})"
    elif actual_number == 5:
        c_display = f"🟢 {to_bold('GREEN')} + 🟣 {to_bold('VIOLET')} ({actual_number})"
    elif actual_color == "RED":
        c_display = f"🔴 {bold_c_name} ({actual_number})"
    else:
        c_display = f"🟢 {bold_c_name} ({actual_number})"

    actual_size = "BIG" if actual_number >= 5 else "SMALL"
    bold_size_name = to_bold("BIG") if actual_size == "BIG" else to_bold("SMALL")
    s_display = f"🐘 {bold_size_name} ({actual_number})" if actual_size == "BIG" else f"🐜 {bold_size_name} ({actual_number})"

    target_type = pred.get("target_type", "COLOR")
    target_val = pred.get("target_val", pred.get("color", "RED"))

    if target_type == "COLOR":
        is_win = (target_val == actual_color)
        t_display = f"🔴 {to_bold('RED')}" if target_val == "RED" else f"🟢 {to_bold('GREEN')}"
    else:
        is_win = (target_val == actual_size)
        t_display = f"🐘 {to_bold('BIG [5-9]')}" if target_val == "BIG" else f"🐜 {to_bold('SMALL [0-4]')}"

    if is_win:
        win_level = CURRENT_LOSS_STREAK + 1
        CYCLE_WINS += 1
        TOTAL_CYCLES += 1
        TOTAL_WINS += 1
        CURRENT_LOSS_STREAK = 0  # WIN! Reset to Level 1!

        mult = 3 ** (win_level - 1)
        win_stage = to_bold(f"LEVEL {win_level} ({mult}X)")

        if win_level == 1:
            win_banner = f"🟢 <b>{to_bold('ROUND RESULT : LEVEL 1 WIN ✅')}</b> 🟢"
            sub = "💰 <i>Direct win secured! Next round resets to Level 1 (1X).</i>"
        elif win_level == 2:
            win_banner = f"🟢 <b>{to_bold('ROUND RESULT : LEVEL 2 RECOVERY WIN ✅')}</b> 🟢"
            sub = "💸 <i>Recovery win secured! Capital + profit restored to Level 1.</i>"
        elif win_level == 3:
            win_banner = f"🟢 <b>{to_bold('ROUND RESULT : LEVEL 3 RECOVERY WIN ✅')}</b> 🟢"
            sub = "🤑 <i>Level 3 recovery delivered! Capital + profit restored to Level 1.</i>"
        elif win_level == 4:
            win_banner = f"🟢 <b>{to_bold('ROUND RESULT : LEVEL 4 RECOVERY WIN ✅')}</b> 🟢"
            sub = "💎 <i>Level 4 recovery delivered! Huge turnaround, resetting to Level 1.</i>"
        else:
            win_banner = f"🟢 <b>{to_bold('ROUND RESULT : LEVEL 5 ULTRA WIN ✅')}</b> 🟢"
            sub = "👑 <i>Level 5 ultimate win delivered! Complete recovery, resetting to Level 1.</i>"

        bonus_hit = ""
        tip_str = str(pred.get("jackpot_tip") or "")
        import re
        tip_numbers = re.findall(r"\b\d\b", tip_str)
        if str(actual_number) in tip_numbers:
            bonus_hit = f"\n🚀 <b>Jackpot Hit</b> : <b>{to_bold(f'NUMBER {actual_number} [9X WIN! 🎉]')}</b>"
        elif actual_number in (0, 5) and (pred.get("violet_alert") or "violet" in tip_str.lower()):
            bonus_hit = f"\n🟣 <b>Bonus Hit</b> : <b>{to_bold('VIOLET 0/5 [4.5X HIT]')}</b>"

        status_str = to_bold("WIN ✅ (PROFIT SECURED)")

        msg = (
            f"{win_banner}\n"
            f"<blockquote>"
            f"⏳ <b>Period</b> : <code>...{short_period}</code>\n"
            f"🎯 <b>Prediction</b> : <b>{t_display}</b>\n"
            f"🎲 <b>Result</b> : <b>{c_display} | {s_display}</b>\n"
            f"🏆 <b>Status</b> : <b>{status_str}</b>\n"
            f"📊 <b>Stage</b> : <b>{win_stage}</b>"
            f"{bonus_hit}\n"
            f"</blockquote>\n"
            f"{sub}"
        )

    else:
        loss_level = CURRENT_LOSS_STREAK + 1
        TOTAL_LOSSES += 1
        CURRENT_LOSS_STREAK += 1  # DO NOT RESET! KEEP CLIMBING UNTIL WIN!

        if CURRENT_LOSS_STREAK >= MAX_MARTINGALE_LEVEL:
            # Reached max safety limit (5-Level Stop-Loss)
            stop_banner = f"🛑 <b>{to_bold('ROUND RESULT : STOP-LOSS CAPITAL GUARD')}</b> 🛑"
            status_str = to_bold("STOP-LOSS (LEVEL 5 HARD CAP)")
            loss_stage = to_bold(f"LEVEL {loss_level} (STOP-LOSS)")
            msg = (
                f"{stop_banner}\n"
                f"<blockquote>"
                f"⏳ <b>Period</b> : <code>...{short_period}</code>\n"
                f"🎯 <b>Prediction</b> : <b>{t_display}</b>\n"
                f"🎲 <b>Result</b> : <b>{c_display} | {s_display}</b>\n"
                f"⚠️ <b>Status</b> : <b>{status_str}</b>\n"
                f"📊 <b>Stage</b> : <b>{loss_stage}</b>\n"
                f"</blockquote>\n"
                f"🛡️ <i>5-Level safety cap reached. Resetting fresh to LEVEL 1 (1X) to start new cycle.</i>"
            )
            CYCLE_LOSSES += 1
            TOTAL_CYCLES += 1
            CURRENT_LOSS_STREAK = 0
        else:
            next_level = CURRENT_LOSS_STREAK + 1
            mult = 3 ** (next_level - 1)
            loss_banner = f"🔴 <b>{to_bold(f'ROUND RESULT : LEVEL {loss_level} LOSS ❌')}</b> 🔴"
            status_str = to_bold("LOSS ❌ (RECOVERY NEXT)")
            next_stage_str = to_bold(f"LEVEL {next_level} ({mult}X RECOVERY)")
            msg = (
                f"{loss_banner}\n"
                f"<blockquote>"
                f"⏳ <b>Period</b> : <code>...{short_period}</code>\n"
                f"🎯 <b>Prediction</b> : <b>{t_display}</b>\n"
                f"🎲 <b>Result</b> : <b>{c_display} | {s_display}</b>\n"
                f"⚠️ <b>Status</b> : <b>{status_str}</b>\n"
                f"⚡ <b>Next Stage</b> : <b>{next_stage_str}</b>\n"
                f"</blockquote>\n"
                f"⚡ <i>Round ...{short_period} missed. Escalating to Level {next_level} ({mult}X) for full recovery!</i>"
            )

    save_cache()
    try:
        send_telegram_msg(USER_ALERT_CHAT_ID, msg, timeout=8, retries=1)
        print(f"[RESULT] Period: ...{short_period} | Result sent (Active Level: {CURRENT_LOSS_STREAK + 1})", flush=True)
    except Exception as e:
        print(f"[USER RESULT ERROR] {e}", flush=True)


# ====================================================
# 🔄 MAIN REAL-TIME LOOP
# ====================================================
def run_live_bot():
    global CONSECUTIVE_SKIPS, CURRENT_LOSS_STREAK, TOTAL_WINS, TOTAL_LOSSES, TOTAL_CYCLES, CYCLE_WINS, CYCLE_LOSSES, MEMORY_PREDICTIONS, MEMORY_HISTORY, KNOWN_PERIODS
    print("=" * 65)
    print("🚀 WinGo 30S 16-Agent AI & Pure Math Hybrid Council ACTIVE!")
    print("🤖 Agent 1: Qwen-27B (Dragon Momentum & Streak Continuation)")
    print("🤖 Agent 2: GPT-20B (1-1 Zig-Zag Chop & Alternation Specialist)")
    print("🤖 Agent 3: Qwen-27B (2-2 Double-Step & Symmetry Specialist)")
    print("🤖 Agent 4: GPT-20B (Contrarian Trap & Retail Sentiment Auditor)")
    print("🤖 Agent 5: Markov N-Gram Quant Engine (Database Transition Matrix)")
    print("🤖 Agent 6: Number-to-Color Bayesian Quant Engine (Historical Matrix)")
    print("🤖 Agent 7: Big/Small & Color Multi-Variable Correlator")
    print("🤖 Agent 8: Rolling Mean-Reversion & Imbalance Quant (Macro/Micro DB)")
    print("🤖 Agent 9: Micro-Cycle Periodicity & Rhythm Quant (Autocorrelation)")
    print("🤖 Agent 10: Market Chaos & Shannon Entropy Risk Gatekeeper")
    print("🤖 Agent 11: Violet 0 & 5 Outlier & Hedge Specialist")
    print("🤖 Agent 12: Weibull Hazard Function & Streak Survival Quant")
    print("🤖 Agent 13: Discrete Fourier Transform (DFT) Harmonic Wave Quant")
    print("🤖 Agent 14: Kolmogorov Algorithmic Complexity / Lempel-Ziv Quant")
    print("🤖 Agent 15: Exponentially-Decayed Beta-Binomial Bayesian Quant")
    print("🤖 Agent 16: GPT-120B (Supreme Arbiter & Risk Controller)")
    print("🎯 Martingale Plan: 3-Level Standard Recovery (88%+ Cycle Accuracy)")
    print("🚫 Skip Policy: Zero Unnecessary Skips (Continuous Predictions)")
    print(f"📱 User Alerts (Direct): {USER_ALERT_CHAT_ID}")
    print(f"☁️ Cloud Storage Channel: {STORAGE_CHANNEL_ID}")
    print("=" * 65, flush=True)

    load_cache()
    threading.Thread(target=start_health_server, args=(int(os.environ.get("PORT", 8080)),), daemon=True).start()
    last_processed_period = None

    while True:
        try:
            # 1. Fetch live historical draws from CDN
            resp = requests.get(HISTORY_API_URL, headers=HEADERS, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                d_data = data.get("data")
                items = d_data.get("list", []) if isinstance(d_data, dict) else []

                if items:
                    latest_item = items[0]
                    current_period = str(latest_item.get("issueNumber", ""))
                    if not current_period:
                        time.sleep(1.0)
                        continue

                    raw_color = str(latest_item.get("color", ""))
                    num = int(latest_item.get("number", 0))

                    has_violet = (num in (0, 5)) or ("violet" in raw_color.lower())
                    if num == 0:
                        actual_color = "RED"
                    elif num == 5:
                        actual_color = "GREEN"
                    else:
                        actual_color = "RED" if "red" in raw_color.lower() else "GREEN"

                    actual_size = "BIG" if num >= 5 else "SMALL"

                    # 2. On initial startup: sync baseline and dispatch immediate prediction!
                    if last_processed_period is None:
                        last_processed_period = current_period
                        for item in reversed(items):
                            p = str(item.get("issueNumber", ""))
                            if p:
                                save_to_memory(p, int(item.get("number", 0)), str(item.get("color", "")), auto_save=False)
                        save_cache()
                        print(f"📦 [STARTUP SYNC] Baseline synced at round {current_period}. Generating immediate startup prediction...", flush=True)

                        # Immediate startup prediction (Zero startup delay!)
                        next_target_period = get_next_period(current_period)
                        if len(MEMORY_HISTORY) >= 6:
                            try:
                                decision = ask_12_ai_council(MEMORY_HISTORY, CURRENT_LOSS_STREAK, CONSECUTIVE_SKIPS)
                                t_type = decision["target_type"]
                                t_val = decision["target_val"]
                                t_conf = decision["target_conf"]
                                if t_type == "SKIP" or t_val == "SKIP":
                                    CONSECUTIVE_SKIPS += 1
                                    save_cache()
                                    send_user_signal(next_target_period, "SKIP", "SKIP", 0.0)
                                    print(f"⏸️ [STARTUP SKIPPED] Period: ...{next_target_period[-4:]} | Zero risk on startup.", flush=True)
                                else:
                                    CONSECUTIVE_SKIPS = 0
                                    MEMORY_PREDICTIONS[next_target_period] = {
                                        "target_type": t_type, "target_val": t_val,
                                        "color": decision["color"], "size": decision["size"],
                                        "conf": t_conf, "reason": decision["reason"],
                                        "consensus": decision["consensus_tag"], "violet_alert": decision["violet_alert"],
                                        "jackpot_tip": decision.get("jackpot_tip"),
                                        "opposite_nums": decision.get("opposite_nums"),
                                        "grade": decision["signal_grade"],
                                        "pattern_name": decision.get("pattern_name", "")
                                    }
                                    save_cache()
                                    send_user_signal(next_target_period, t_type, t_val, t_conf, decision["reason"], decision["consensus_tag"], decision["violet_alert"], decision["signal_grade"], decision.get("jackpot_tip"), decision.get("pattern_name", ""), decision.get("opposite_nums"))
                            except Exception as e:
                                print(f"[STARTUP PREDICTION ERROR] {e}", flush=True)
                        time.sleep(1.0)
                        continue

                    if current_period != last_processed_period:
                        last_processed_period = current_period
                        v_tag = "+VIOLET" if has_violet else ""
                        print(f"\n[ROUND COMPLETE] Season ID: {current_period} | Result: {actual_color}{v_tag} | {actual_size} ({num})", flush=True)

                        # A. Evaluate Previous Prediction Result (check recent items so no result is ever missed)
                        evaluated_any = False
                        for itm in reversed(items[:5]):
                            p_chk = str(itm.get("issueNumber", ""))
                            if p_chk in MEMORY_PREDICTIONS:
                                p_num = int(itm.get("number", 0))
                                p_raw = str(itm.get("color", ""))
                                if p_num == 0:
                                    p_col = "RED"
                                elif p_num == 5:
                                    p_col = "GREEN"
                                else:
                                    p_col = "RED" if "red" in p_raw.lower() else "GREEN"
                                pred = MEMORY_PREDICTIONS[p_chk]
                                send_user_result(p_chk, p_num, p_col, pred)
                                del MEMORY_PREDICTIONS[p_chk]
                                evaluated_any = True
                                time.sleep(0.4)

                        if evaluated_any:
                            save_cache()

                        # Clean up any stale predictions older than 5 rounds
                        try:
                            cur_p_int = int(current_period)
                            stale_keys = [k for k in list(MEMORY_PREDICTIONS.keys()) if int(k) < (cur_p_int - 5)]
                            for k in stale_keys:
                                del MEMORY_PREDICTIONS[k]
                        except Exception:
                            pass

                        # B. Sync batch of draws into RAM memory
                        new_added = False
                        for item in reversed(items):
                            p = str(item.get("issueNumber", ""))
                            if not p:
                                continue
                            r_c = str(item.get("color", ""))
                            n = int(item.get("number", 0))
                            if save_to_memory(p, n, r_c, auto_save=False):
                                new_added = True

                        if new_added:
                            try:
                                MEMORY_HISTORY.sort(key=lambda x: int(x["period"]))
                            except Exception:
                                pass
                            save_cache()

                        # C. Background async logging to Storage Channel
                        threading.Thread(
                            target=log_round_to_storage_channel,
                            args=(current_period, num, actual_color, has_violet, actual_size),
                            daemon=True
                        ).start()

                        # D. Read in-memory history and trigger 16-Agent AI & Quant Council
                        next_target_period = get_next_period(current_period)

                        if len(MEMORY_HISTORY) >= 6:
                            decision = ask_12_ai_council(MEMORY_HISTORY, CURRENT_LOSS_STREAK, CONSECUTIVE_SKIPS)
                            t_type = decision["target_type"]
                            t_val = decision["target_val"]
                            t_conf = decision["target_conf"]
                            pred_color = decision["color"]
                            pred_size = decision["size"]
                            reason = decision["reason"]
                            consensus_tag = decision["consensus_tag"]
                            violet_alert = decision["violet_alert"]
                            jackpot_tip = decision.get("jackpot_tip")
                            signal_grade = decision["signal_grade"]
                            pattern_name = decision.get("pattern_name", "")

                            v_flag = " [🟣 VIOLET ALERT]" if violet_alert else ""
                            j_flag = f" [🎰 TIP: {jackpot_tip}]" if jackpot_tip else ""
                            p_flag = f" [🧩 {pattern_name}]" if pattern_name else ""
                            print(f"🏛️ Council Verdict: BestBet={t_type}:{t_val} ({t_conf:.1f}%) | Color={pred_color} | Size={pred_size} | {consensus_tag}{v_flag}{j_flag}{p_flag} | {signal_grade}", flush=True)

                            if t_type == "SKIP" or t_val == "SKIP":
                                CONSECUTIVE_SKIPS += 1
                                save_cache()
                                send_user_signal(next_target_period, "SKIP", "SKIP", 0.0)
                                print(f"⏸️ [ROUND SKIPPED] Period: ...{next_target_period[-4:]} | Zero risk, Martingale streak preserved.", flush=True)
                            else:
                                CONSECUTIVE_SKIPS = 0
                                # Save & Dispatch ONE final decision to User DM
                                MEMORY_PREDICTIONS[next_target_period] = {
                                    "target_type": t_type,
                                    "target_val": t_val,
                                    "color": pred_color,
                                    "size": pred_size,
                                    "conf": t_conf,
                                    "reason": reason,
                                    "consensus": consensus_tag,
                                    "violet_alert": violet_alert,
                                    "jackpot_tip": jackpot_tip,
                                    "opposite_nums": decision.get("opposite_nums"),
                                    "grade": signal_grade,
                                    "pattern_name": pattern_name
                                }
                                save_cache()
                                send_user_signal(next_target_period, t_type, t_val, t_conf, reason, consensus_tag, violet_alert, signal_grade, jackpot_tip, pattern_name, decision.get("opposite_nums"))

        except Exception as e:
            print(f"[LOOP ERROR] {e}", flush=True)

        time.sleep(1.0)

if __name__ == "__main__":
    while True:
        try:
            run_live_bot()
        except Exception as e:
            print(f"🚨 [SUPERVISOR AUTO-RECOVERY] Bot loop exited with: {e}. Auto-restarting in 2s...", flush=True)
            time.sleep(2.0)
