#!/usr/bin/env python3
import time
import json
import os
import math
import threading
import requests
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

# 5-AI Council Models
MODEL_QWEN = "qwen/qwen3.8-27b"            # High-speed specialized reasoning
MODEL_GPT20B = "qwen/qwen3.8-27b"           # Structural & Quant pattern reasoning (Qwen backed for zero-rate-limits)
MODEL_GPT120B = "openai/gpt-oss-120b"      # Supreme Arbiter & Multi-Agent Synthesizer

HISTORY_API_URL = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.environ.get("CACHE_FILE", os.path.join(BASE_DIR, "history_cache.json"))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"healthy","service":"wingo_council_bot"}\n')

    def log_message(self, format, *args):
        pass

def start_health_server(port=8080):
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        print(f"🌐 [HEALTH SERVER] Active on port {port}", flush=True)
        server.serve_forever()
    except Exception as e:
        print(f"⚠️ [HEALTH SERVER NOTICE] {e}", flush=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:154.0) Gecko/20100101 Firefox/154.0",
    "Accept": "application/json"
}

# ====================================================
# ☁️ ZERO-DEVICE-STORAGE (IN-MEMORY + LOCAL CACHE)
# ====================================================
MEMORY_HISTORY = []      # List of {"period": ..., "num": ..., "color": ..., "size": ..., "has_violet": ...}
KNOWN_PERIODS = set()    # O(1) set to prevent duplicate iteration
MEMORY_PREDICTIONS = {}  # {target_period: {"color": ..., "conf": ..., "reason": ..., "consensus": ..., "violet_alert": ...}}

CURRENT_LOSS_STREAK = 0
TOTAL_WINS = 0
TOTAL_LOSSES = 0
TOTAL_SKIPS = 0
CONSECUTIVE_SKIPS = 0

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
    global MEMORY_HISTORY, KNOWN_PERIODS
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

def save_cache():
    try:
        tmp_file = f"{CACHE_FILE}.tmp"
        with open(tmp_file, "w") as f:
            json.dump(MEMORY_HISTORY, f)
        os.replace(tmp_file, CACHE_FILE)
    except Exception:
        pass

def send_telegram_msg(chat_id, text, timeout=8, retries=1):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            if r.status_code == 200:
                return True
            else:
                print(f"[TELEGRAM API ERROR] Status {r.status_code}: {r.text}", flush=True)
        except Exception:
            if attempt < retries:
                time.sleep(0.5)
                continue
            raise
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
# 📊 MATHEMATICAL MARKET STRUCTURE & PATTERN ENGINE
# ====================================================
def detect_market_patterns(history_items):
    """
    Extracts structural market patterns & computes deterministic database quants:
    - Dragon streak (streak length and color)
    - 1-1 Alternating Chop
    - 2-2 Double-Step pattern
    - Quant 5: Markov N-Gram Matrix across ALL historical records
    - Quant 6: Winning Number to Color Transition Matrix
    - Quant 7: Big/Small & Color Multi-Variable Matrix
    - Quant 8: Rolling Mean-Reversion Imbalance
    - Quant 9: Micro-Cycle Autocorrelation Rhythm
    - Quant 10: Shannon Entropy & Chaos Risk
    - Quant 11: Violet 0 & 5 Outlier & Hedge Engine
    """
    if not history_items:
        return {
            "streak_color": None, "streak_len": 0, "is_alt": False,
            "alt_len": 0, "is_double": False, "recommended": None,
            "conf": 50.0, "pattern_desc": "No history", "recent_compact": "",
            "violet_due": False, "rounds_since_violet": 0,
            "quants": {}
        }

    colors = [it.get("color", "") for it in history_items]
    nums = [int(it.get("num", 0)) for it in history_items]
    sizes = [it.get("size", "BIG" if int(it.get("num", 0)) >= 5 else "SMALL") for it in history_items]
    last_c = colors[-1]
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

    # 3. Double-Double (2-2 pattern: RR-GG-RR)
    is_double = False
    if len(colors) >= 4 and colors[-1] == colors[-2] and colors[-3] == colors[-4] and colors[-1] != colors[-3]:
        is_double = True

    # 4. Quant 5: Markov N-gram Transitions (Across ALL historical database records)
    t3 = defaultdict(lambda: {"RED": 0, "GREEN": 0})
    for i in range(len(colors) - 3):
        t3[tuple(colors[i:i + 3])][colors[i + 3]] += 1
    last3 = tuple(colors[-3:]) if len(colors) >= 3 else ()
    c3 = t3.get(last3, {"RED": 0, "GREEN": 0})
    tot3 = c3["RED"] + c3["GREEN"]
    if tot3 >= 2:
        ng_col = "RED" if c3["RED"] >= c3["GREEN"] else "GREEN"
        ng_conf = round(max(c3["RED"], c3["GREEN"]) / tot3 * 100, 1)
        q5_ngram = (ng_col, ng_conf, f"Database state {last3} resolved to {ng_col} {max(c3['RED'], c3['GREEN'])}/{tot3} times ({ng_conf}%)")
    else:
        q5_ngram = (last_c, 55.0, "Low state occurrences; default momentum")

    # 5. Quant 6: Number-to-Color Transition (Across ALL historical database records)
    num_trans = defaultdict(lambda: {"RED": 0, "GREEN": 0})
    for i in range(len(nums) - 1):
        num_trans[nums[i]][colors[i + 1]] += 1
    cn = num_trans.get(last_num, {"RED": 0, "GREEN": 0})
    tot_n = cn["RED"] + cn["GREEN"]
    if tot_n >= 2:
        nt_col = "RED" if cn["RED"] >= cn["GREEN"] else "GREEN"
        nt_conf = round(max(cn["RED"], cn["GREEN"]) / tot_n * 100, 1)
        q6_num = (nt_col, nt_conf, f"Winning Number {last_num} historically yielded {nt_col} {max(cn['RED'], cn['GREEN'])}/{tot_n} times ({nt_conf}%)")
    else:
        q6_num = (last_c, 55.0, f"Number {last_num} sample small; neutral edge")

    # 6. Quant 7: Big/Small & Color Multi-Variable Correlator
    bs_trans = defaultdict(lambda: {"RED": 0, "GREEN": 0})
    for i in range(len(sizes) - 1):
        bs_trans[(sizes[i], colors[i])][colors[i + 1]] += 1
    last_bs = (sizes[-1], colors[-1])
    cbs = bs_trans.get(last_bs, {"RED": 0, "GREEN": 0})
    tot_bs = cbs["RED"] + cbs["GREEN"]
    if tot_bs >= 2:
        bs_col = "RED" if cbs["RED"] >= cbs["GREEN"] else "GREEN"
        bs_conf = round(max(cbs["RED"], cbs["GREEN"]) / tot_bs * 100, 1)
        q7_bs = (bs_col, bs_conf, f"Composite state {last_bs} transitioned to {bs_col} {max(cbs['RED'], cbs['GREEN'])}/{tot_bs} times ({bs_conf}%)")
    else:
        q7_bs = (last_c, 55.0, "Composite neutral")

    # 7. Quant 8: Rolling Mean-Reversion & Imbalance (Last 30 rounds)
    recent_30 = colors[-30:] if len(colors) >= 30 else colors
    r_count = recent_30.count("RED")
    g_count = recent_30.count("GREEN")
    if r_count >= g_count + 4:
        q8_mr = ("GREEN", 68.0, f"RED overbought in last 30 ({r_count} vs {g_count}); mean-reversion points to GREEN")
    elif g_count >= r_count + 4:
        q8_mr = ("RED", 68.0, f"GREEN overbought in last 30 ({g_count} vs {r_count}); mean-reversion points to RED")
    else:
        q8_mr = (last_c, 52.0, f"Balanced 30-round distribution ({r_count}R / {g_count}G); trend maintained")

    # 8. Quant 9: Micro-Cycle Periodicity & Rhythm (Lag-2 & Lag-3 harmonic autocorrelation)
    if len(colors) >= 6:
        lag2_matches = sum(1 for i in range(len(colors) - 10, len(colors)) if colors[i] == colors[i - 2])
        if lag2_matches >= 6:
            rhy_col = colors[-2]
            q9_rhy = (rhy_col, 70.0, f"Strong Lag-2 cyclical harmonic active ({lag2_matches}/10 matches)")
        else:
            q9_rhy = (last_c, 54.0, "Micro-cycle rhythm in balance")
    else:
        q9_rhy = (last_c, 50.0, "Insufficient cycle span")

    # 9. Quant 10: Market Chaos & Shannon Entropy Gatekeeper
    recent_10 = colors[-10:] if len(colors) >= 10 else colors
    p_r = recent_10.count("RED") / len(recent_10)
    p_g = recent_10.count("GREEN") / len(recent_10)
    entropy = 0.0
    for p in (p_r, p_g):
        if p > 0:
            entropy -= p * math.log2(p)
    if entropy >= 0.98 and streak_len == 1 and alt_len <= 2:
        q10_ent = ("WAIT", 0.0, f"Peak Shannon Entropy ({entropy:.2f}) indicates random chop; capital shield advised")
    else:
        ent_col = last_c if streak_len >= 2 else ("RED" if p_r >= p_g else "GREEN")
        q10_ent = (ent_col, 62.0, f"Controlled entropy level ({entropy:.2f}); orderly structure")

    # 10. Quant 11: Violet (0 & 5) Dormancy & Outlier Specialist
    rounds_since_violet = 0
    for it in reversed(history_items):
        if it.get("has_violet", False) or int(it.get("num", -1)) in (0, 5):
            break
        rounds_since_violet += 1
    violet_due = (rounds_since_violet >= 12)
    if violet_due:
        v_col = "RED" if last_num in (1, 2, 3, 4) else "GREEN"
        q11_vio = (v_col, 75.0, f"Violet overdue ({rounds_since_violet} rounds dormant); hedge recommended on 0/5")
    else:
        q11_vio = (last_c, 55.0, f"Violet cycle normal ({rounds_since_violet} rounds dormant)")

    # Compile descriptive pattern tags
    desc = []
    if streak_len >= 3:
        desc.append(f"🔥 Dragon Trend ({last_c} x {streak_len})")
    elif streak_len == 2:
        desc.append(f"Pair ({last_c} x 2)")

    if alt_len >= 3:
        desc.append(f"⚡ 1-1 Alternating Chop ({alt_len} rounds)")
    if is_double:
        desc.append("🔄 2-2 Double Pattern")
    desc.append(f"📈 N-Gram Math: {q5_ngram[0]} ({q5_ngram[1]}%)")
    if violet_due:
        desc.append(f"🟣 Violet Overdue ({rounds_since_violet} rounds dormant)")

    recent_12 = history_items[-12:] if len(history_items) >= 12 else history_items
    compact_parts = []
    for it in recent_12:
        num = int(it.get("num", 0))
        c_code = it.get("color", "")[:1]
        v_tag = "+V" if it.get("has_violet") or num in (0, 5) else ""
        compact_parts.append(f"{c_code}{v_tag}({num})")
    recent_compact = ", ".join(compact_parts)

    return {
        "streak_color": last_c,
        "streak_len": streak_len,
        "is_alt": alt_len >= 3,
        "alt_len": alt_len,
        "is_double": is_double,
        "pattern_desc": " | ".join(desc) if desc else "Neutral / Mixed Cycle",
        "recent_compact": recent_compact,
        "violet_due": violet_due,
        "rounds_since_violet": rounds_since_violet,
        "quants": {
            "q5": q5_ngram,
            "q6": q6_num,
            "q7": q7_bs,
            "q8": q8_mr,
            "q9": q9_rhy,
            "q10": q10_ent,
            "q11": q11_vio
        }
    }

# ====================================================
# 🧠 12-AI COLLABORATIVE COUNCIL (INTER-AGENT DEBATE)
# ====================================================
def ask_12_ai_council(history_items, current_loss_streak=0):
    """
    12-AI Collaborative Council Architecture:
    • Specialist 1 (Qwen-27B): Dragon & Trend Momentum Specialist
    • Specialist 2 (GPT-20B): 1-1 Zig-Zag Chop & Alternation Specialist
    • Specialist 3 (Qwen-27B): 2-2 Double-Step & Harmonic Symmetry Specialist
    • Specialist 4 (GPT-20B): Contrarian Trap & Retail Sentiment Auditor
    • Specialist 5: Deep Markov N-Gram Quant Engine (Database Transition Matrix)
    • Specialist 6: Number-to-Color Bayesian Quant Engine (Historical Database Matrix)
    • Specialist 7: Big/Small & Color Multi-Variable Correlator
    • Specialist 8: Rolling Mean-Reversion & Imbalance Quant (30-round window)
    • Specialist 9: Micro-Cycle Periodicity & Rhythm Quant (Autocorrelation)
    • Specialist 10: Market Chaos & Shannon Entropy Risk Gatekeeper
    • Specialist 11: Violet 0 & 5 Outlier & Hedge Specialist
    • Agent 12 (GPT-120B): Supreme Arbiter & Risk Controller (Presides, debates, issues binding ruling)
    """
    global CONSECUTIVE_SKIPS
    p_info = detect_market_patterns(history_items)
    recent_str = p_info["recent_compact"]
    pattern_str = p_info["pattern_desc"]
    last_color = p_info["streak_color"]
    streak_len = p_info["streak_len"]
    violet_due = p_info["violet_due"]
    quants = p_info.get("quants", {})

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    # --- Phase 1: 4 Neural LLM Specialists Consult in Parallel ---
    specialist_tasks = [
        (
            "Agent 1 (Dragon Momentum: Qwen-27B)",
            MODEL_QWEN,
            (
                f"You are Agent 1 (Dragon Momentum Specialist) on the 12-AI WinGo Council.\n"
                f"Recent rounds: {recent_str}\n"
                f"Market Structure: {pattern_str}\n"
                f"Mandate: If an active Dragon streak (3+ {last_color}) is running, ALWAYS follow momentum ({last_color}) unless streak is 7+.\n"
                f"Return JSON ONLY: {{\"color\": \"RED\" or \"GREEN\", \"conf\": 75, \"arg\": \"1 brief sentence\"}}"
            )
        ),
        (
            "Agent 2 (1-1 Chop: GPT-20B)",
            MODEL_GPT20B,
            (
                f"You are Agent 2 (1-1 Chop Specialist) on the 12-AI WinGo Council.\n"
                f"Recent rounds: {recent_str}\n"
                f"Market Structure: {pattern_str}\n"
                f"Mandate: If 1-1 alternation (R-G-R-G) is active, follow the rhythm (predict opposite of last).\n"
                f"Return JSON ONLY: {{\"color\": \"RED\" or \"GREEN\", \"conf\": 75, \"arg\": \"1 brief sentence\"}}"
            )
        ),
        (
            "Agent 3 (2-2 Symmetry: Qwen-27B)",
            MODEL_QWEN,
            (
                f"You are Agent 3 (2-2 Symmetry Specialist) on the 12-AI WinGo Council.\n"
                f"Recent rounds: {recent_str}\n"
                f"Market Structure: {pattern_str}\n"
                f"Mandate: Identify paired steps (RR-GG) and mirror patterns. Predict the next step of the cycle.\n"
                f"Return JSON ONLY: {{\"color\": \"RED\" or \"GREEN\", \"conf\": 75, \"arg\": \"1 brief sentence\"}}"
            )
        ),
        (
            "Agent 4 (Contrarian Trap: GPT-20B)",
            MODEL_GPT20B,
            (
                f"You are Agent 4 (Contrarian Trap Hunter) on the 12-AI WinGo Council.\n"
                f"Recent rounds: {recent_str}\n"
                f"Market Structure: {pattern_str}\n"
                f"Mandate: Identify false breakouts and retail traps. Challenge herd bias when a trend shows exhaustion.\n"
                f"Return JSON ONLY: {{\"color\": \"RED\" or \"GREEN\", \"conf\": 75, \"arg\": \"1 brief sentence\"}}"
            )
        )
    ]

    def query_specialist(task_info):
        agent_name, model_name, prompt_txt = task_info
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json={
                "model": model_name,
                "messages": [{"role": "user", "content": prompt_txt}],
                "response_format": {"type": "json_object"}
            }, timeout=3.3)
            if r.status_code == 200:
                res = json.loads(r.json()["choices"][0]["message"]["content"])
                c = str(res.get("color", "")).upper()
                if c in ("RED", "GREEN"):
                    return {
                        "name": agent_name,
                        "color": c,
                        "conf": float(res.get("conf", 75.0)),
                        "arg": res.get("arg", "")
                    }
        except Exception:
            pass

        # Algorithmic fallback for specialist
        c_fall = last_color if streak_len >= 3 else ("RED" if quants.get("q5", ["RED"])[0] == "RED" else "GREEN")
        return {"name": agent_name, "color": c_fall or "RED", "conf": 70.0, "arg": "Empirical pattern fallback"}

    with ThreadPoolExecutor(max_workers=4) as executor:
        llm_specialists = list(executor.map(query_specialist, specialist_tasks))

    # --- Phase 2: Compile All 11 Specialists (4 LLM + 7 Database Quants) ---
    q5 = quants.get("q5", (last_color, 60.0, "N-Gram fallback"))
    q6 = quants.get("q6", (last_color, 55.0, "Number transition fallback"))
    q7 = quants.get("q7", (last_color, 55.0, "Big/Small transition fallback"))
    q8 = quants.get("q8", (last_color, 55.0, "Mean-reversion fallback"))
    q9 = quants.get("q9", (last_color, 55.0, "Periodicity fallback"))
    q10 = quants.get("q10", (last_color, 55.0, "Entropy fallback"))
    q11 = quants.get("q11", (last_color, 55.0, "Violet fallback"))

    all_11_specialists = [
        llm_specialists[0],
        llm_specialists[1],
        llm_specialists[2],
        llm_specialists[3],
        {"name": f"Agent 5 (N-Gram Markov Quant [{len(history_items)} Rounds])", "color": q5[0], "conf": q5[1], "arg": q5[2]},
        {"name": "Agent 6 (Number-to-Color Quant)", "color": q6[0], "conf": q6[1], "arg": q6[2]},
        {"name": "Agent 7 (Big/Small & Color Correlator)", "color": q7[0], "conf": q7[1], "arg": q7[2]},
        {"name": "Agent 8 (Mean-Reversion Imbalance Quant)", "color": q8[0], "conf": q8[1], "arg": q8[2]},
        {"name": "Agent 9 (Micro-Cycle Periodicity Quant)", "color": q9[0], "conf": q9[1], "arg": q9[2]},
        {"name": "Agent 10 (Shannon Entropy Risk Gatekeeper)", "color": q10[0], "conf": q10[1], "arg": q10[2]},
        {"name": "Agent 11 (Violet 0/5 Outlier Specialist)", "color": q11[0], "conf": q11[1], "arg": q11[2]}
    ]

    spec_summary = "\n".join([
        f"- {s['name']}: Proposes {s['color']} ({s['conf']:.0f}%) -> Argument: \"{s['arg']}\""
        for s in all_11_specialists
    ])

    red_votes = sum(1 for s in all_11_specialists if s["color"] == "RED")
    green_votes = sum(1 for s in all_11_specialists if s["color"] == "GREEN")
    wait_votes = sum(1 for s in all_11_specialists if s["color"] == "WAIT")

    # --- Phase 3: Council Debate & Supreme Arbiter Ruling ---
    prompt_arbiter = (
        f"You are Agent 12 (Supreme Arbiter) presiding over the 12-AI WinGo Council.\n"
        f"Recent sequence: {recent_str}\n"
        f"Market Structure: {pattern_str}\n"
        f"Current Consecutive Loss Streak: {current_loss_streak}\n"
        f"Violet Dormancy: {p_info['rounds_since_violet']} rounds (Overdue: {violet_due})\n"
        f"Specialists Debate:\n{spec_summary}\n"
        f"Vote Tally: RED={red_votes} | GREEN={green_votes} | WAIT={wait_votes}\n\n"
        f"Supreme Arbiter Directives:\n"
        f"1. Render the final decision: 'RED' or 'GREEN'.\n"
        f"2. You may ONLY choose 'WAIT' if specialists are deadlocked (abs diff <= 1) AND current_loss_streak >= 3 AND consecutive skips == 0.\n"
        f"3. In all other scenarios, choose the stronger probability ('RED' or 'GREEN').\n\n"
        f"Return JSON ONLY:\n"
        f"{{\n"
        f'  "final_color": "RED" or "GREEN" or "WAIT",\n'
        f'  "confidence": 85,\n'
        f'  "vote_tally": "Council Consensus",\n'
        f'  "violet_alert": false,\n'
        f'  "debate_summary": "1 concise sentence summarizing how consensus was reached."\n'
        f"}}"
    )

    # Try Arbiter models (GPT-120B first, fallback to Qwen-27B):
    for arb_model in [MODEL_GPT120B, MODEL_QWEN]:
        try:
            r_arb = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json={
                "model": arb_model,
                "messages": [{"role": "user", "content": prompt_arbiter}],
                "response_format": {"type": "json_object"}
            }, timeout=3.5)
            if r_arb.status_code == 200:
                res_arb = json.loads(r_arb.json()["choices"][0]["message"]["content"])
                decision = str(res_arb.get("final_color", "")).upper()
                if decision in ("RED", "GREEN", "WAIT"):
                    # Prevent skips unless in an active high loss streak (>= 3) and no consecutive skips
                    if decision == "WAIT" and (current_loss_streak < 3 or CONSECUTIVE_SKIPS >= 1):
                        decision = "RED" if red_votes >= green_votes else "GREEN"

                    conf = float(res_arb.get("confidence", 85.0))
                    tally = res_arb.get("vote_tally", f"{max(red_votes, green_votes)}-{min(red_votes, green_votes)} Consensus")
                    v_arb = bool(res_arb.get("violet_alert", False))
                    v_alert = (v_arb and p_info['rounds_since_violet'] >= 10) or violet_due
                    summary = res_arb.get("debate_summary", "12-AI Council synthesized final consensus.")
                    return decision, conf, summary, tally, v_alert
        except Exception:
            continue

    # High-Precision Local Quant Fallback:
    if red_votes > green_votes:
        w_col = "RED"
        w_v, l_v = red_votes, green_votes
    elif green_votes > red_votes:
        w_col = "GREEN"
        w_v, l_v = green_votes, red_votes
    else:
        # Tie-breaker using Markov N-Gram or Streak Momentum
        q5_col = quants.get("q5", (last_color or "RED",))[0]
        w_col = q5_col if q5_col in ("RED", "GREEN") else (last_color or "RED")
        w_v, l_v = 6, 5

    vote_ratio = w_v / max(1, (w_v + l_v))
    calc_conf = round(72.0 + (vote_ratio * 18.0), 1)

    # 🛡️ Capital Shield (SKIP):
    # ONLY skip if:
    # 1. Previous round was NOT skipped (CONSECUTIVE_SKIPS == 0)
    # 2. AND we are suffering a loss streak >= 3
    # 3. AND the votes are deadlocked (abs diff <= 1) OR Quant 10 indicates extreme entropy
    is_entropy_wait = (quants.get("q10", ("OK", 0))[0] == "WAIT")
    is_vote_tie = abs(red_votes - green_votes) <= 1

    if CONSECUTIVE_SKIPS == 0 and current_loss_streak >= 3 and (is_vote_tie or is_entropy_wait):
        return "WAIT", 0.0, "Specialists deadlocked under adverse loss streak; 1-round Capital Shield activated.", "🛡️ Capital Shield (SKIP)", violet_due

    # Otherwise ALWAYS predict winner:
    if w_v >= 8:
        consensus_tag = f"🏛️ Council Super-Majority ({w_v}-{l_v})"
    else:
        consensus_tag = f"⚖️ Council Plurality ({w_v}-{l_v})"

    summary = f"12-Agent Council majority voted {w_col} ({w_v}-{l_v})."
    return w_col, calc_conf, summary, consensus_tag, violet_due

# ====================================================
# 🚀 USER SIGNALS (SENT DIRECTLY TO USER DM)
# ====================================================
def send_user_signal(target_period, color, confidence, reason, consensus_tag="12-AI Council", violet_alert=False):
    short_period = target_period[-4:] if len(target_period) >= 4 else target_period

    if color == "WAIT":
        msg = (
            f"⏸️ <b>WinGo 30S Capital Shield</b> | <code>...{short_period}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>12-AI Council Action</b> : <b>⏸️ SKIP / WAIT</b>\n"
            f"⚠️ <b>Risk Filter</b>          : <code>Split Consensus / Turbulent Cycle</code>\n"
            f"💬 <b>Debate Summary</b>       : <i>\"{reason}\"</i>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>Capital protected. Awaiting high-conviction pattern.</i>"
        )
    else:
        c_emoji = "🔴 RED" if color == "RED" else "🟢 GREEN"
        v_alert_line = ""
        if violet_alert:
            target_num = "0" if color == "RED" else "5"
            v_alert_line = f"🟣 <b>Violet Watch</b>        : ⚠️ <b>High Chance of {target_num} (Violet)!</b>\n"

        msg = (
            f"🎯 <b>WinGo 30S 12-AI Council Signal</b> | <code>...{short_period}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👉 <b>Predicted Color</b>     : <b>{c_emoji}</b>\n"
            f"{v_alert_line}"
            f"📊 <b>Confidence</b>          : <code>{confidence:.1f}%</code>\n"
            f"🏛️ <b>Council Verdict</b>     : <b>{consensus_tag}</b>\n"
            f"💬 <b>Debate Summary</b>      : <i>\"{reason}\"</i>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

    try:
        send_telegram_msg(USER_ALERT_CHAT_ID, msg, timeout=8, retries=1)
        print(f"👉 [DM SIGNAL SENT] Period: ...{short_period} | {color} ({confidence:.1f}%) | {consensus_tag}", flush=True)
    except Exception as e:
        print(f"[USER ALERT ERROR] {e}", flush=True)

def send_user_result(period, actual_number, actual_color, pred):
    global CURRENT_LOSS_STREAK, TOTAL_WINS, TOTAL_LOSSES, TOTAL_SKIPS, CONSECUTIVE_SKIPS
    short_period = period[-4:] if len(period) >= 4 else period

    # Mixed Color formatting
    is_violet = (actual_number in (0, 5))
    if actual_number == 0:
        c_display = "🔴 RED + 🟣 VIOLET (0)"
    elif actual_number == 5:
        c_display = "🟢 GREEN + 🟣 VIOLET (5)"
    elif actual_color == "RED":
        c_display = f"🔴 RED ({actual_number})"
    else:
        c_display = f"🟢 GREEN ({actual_number})"

    if pred.get("color") == "WAIT":
        TOTAL_SKIPS += 1
        CONSECUTIVE_SKIPS += 1
        CURRENT_LOSS_STREAK = 0  # CRUCIAL: Breaks the loss cycle deadlock!
        msg = (
            f"🛡️ <b>ROUND SKIPPED</b> | Period: <code>...{short_period}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎲 Actual Result : <b>{c_display}</b>\n"
            f"✅ <b>Capital Protected</b>: Skipped turbulent round. Resuming predictions next round!\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        try:
            send_telegram_msg(USER_ALERT_CHAT_ID, msg, timeout=8, retries=1)
            print(f"[RESULT] Period: ...{short_period} | SKIPPED (Streak reset)", flush=True)
        except Exception as e:
            print(f"[USER RESULT ERROR] {e}", flush=True)
        return

    CONSECUTIVE_SKIPS = 0

    # In WinGo, predicting RED and getting 0 is a win (half payout for color).
    # Predicting GREEN and getting 5 is a win (half payout for color).
    predicted_color = pred["color"]
    color_win = (predicted_color == actual_color)

    if color_win:
        CURRENT_LOSS_STREAK = 0
        TOTAL_WINS += 1
        if is_violet:
            if pred.get("violet_alert"):
                header = "🟣 <b>JACKPOT VIOLET WIN (4.5x Payout)!</b>"
            else:
                header = "🟡 <b>HALF WIN (1.5x Payout - Mixed Violet)</b>"
        else:
            header = "✅ <b>WIN (2x Payout)</b>"
    else:
        CURRENT_LOSS_STREAK += 1
        TOTAL_LOSSES += 1
        header = f"❌ <b>LOSS (Level {CURRENT_LOSS_STREAK})</b>"
        if CURRENT_LOSS_STREAK >= 5:
            header += " ⚠️ [RISK ALERT]"

    win_rate = (TOTAL_WINS / (TOTAL_WINS + TOTAL_LOSSES) * 100) if (TOTAL_WINS + TOTAL_LOSSES) > 0 else 0.0

    msg = (
        f"{header} | Period: <code>...{short_period}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎲 Actual Result : <b>{c_display}</b>\n"
        f"🎯 Predicted     : <b>{predicted_color}</b>\n"
        f"📈 Session Stats : <code>{TOTAL_WINS}W - {TOTAL_LOSSES}L ({win_rate:.1f}%)</code>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    try:
        send_telegram_msg(USER_ALERT_CHAT_ID, msg, timeout=8, retries=1)
        print(f"[RESULT] Period: ...{short_period} | {header}", flush=True)
    except Exception as e:
        print(f"[USER RESULT ERROR] {e}", flush=True)

# ====================================================
# 🔄 MAIN REAL-TIME LOOP
# ====================================================
def run_live_bot():
    print("=" * 65)
    print("🚀 WinGo 30S 12-AI Collaborative Council ACTIVE!")
    print("🤖 Agent 1: Qwen-27B (Dragon Momentum & Streak Continuation)")
    print("🤖 Agent 2: GPT-20B (1-1 Zig-Zag Chop & Alternation Specialist)")
    print("🤖 Agent 3: Qwen-27B (2-2 Double-Step & Symmetry Specialist)")
    print("🤖 Agent 4: GPT-20B (Contrarian Trap & Retail Sentiment Auditor)")
    print("🤖 Agent 5: Markov N-Gram Quant Engine (Database Transition Matrix)")
    print("🤖 Agent 6: Number-to-Color Bayesian Quant Engine (Historical Matrix)")
    print("🤖 Agent 7: Big/Small & Color Multi-Variable Correlator")
    print("🤖 Agent 8: Rolling Mean-Reversion & Imbalance Quant (30-round window)")
    print("🤖 Agent 9: Micro-Cycle Periodicity & Rhythm Quant (Autocorrelation)")
    print("🤖 Agent 10: Market Chaos & Shannon Entropy Risk Gatekeeper")
    print("🤖 Agent 11: Violet 0 & 5 Outlier & Hedge Specialist")
    print("🤖 Agent 12: GPT-120B (Supreme Arbiter & Risk Controller)")
    print("🟣 Mixed Color Engine: 0 (RED+VIOLET) & 5 (GREEN+VIOLET) ACTIVE")
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

                    # 2. When a round finishes:
                    if current_period != last_processed_period:
                        last_processed_period = current_period
                        v_tag = "+VIOLET" if has_violet else ""
                        print(f"\n[ROUND COMPLETE] Season ID: {current_period} | Result: {actual_color}{v_tag} | {actual_size} ({num})", flush=True)

                        # A. Evaluate Previous Prediction Result
                        if current_period in MEMORY_PREDICTIONS:
                            pred = MEMORY_PREDICTIONS[current_period]
                            send_user_result(current_period, num, actual_color, pred)
                            del MEMORY_PREDICTIONS[current_period]
                            time.sleep(0.4)  # Prevent Telegram burst rate limits

                        # Clean up any stale predictions older than current_period (prevents memory leak)
                        try:
                            cur_p_int = int(current_period)
                            stale_keys = [k for k in list(MEMORY_PREDICTIONS.keys()) if int(k) < cur_p_int]
                            for k in stale_keys:
                                del MEMORY_PREDICTIONS[k]
                        except Exception:
                            pass

                        # B. Sync batch of draws into RAM memory (Batch write)
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

                        # D. Read in-memory history and trigger 12-AI Council Debate
                        next_target_period = get_next_period(current_period)

                        if len(MEMORY_HISTORY) >= 6:
                            # 12 AI aapas me debate karke final prediction decide karte hain
                            pred_color, final_conf, reason, consensus_tag, violet_alert = ask_12_ai_council(
                                MEMORY_HISTORY, CURRENT_LOSS_STREAK
                            )

                            v_flag = " [🟣 VIOLET ALERT]" if violet_alert else ""
                            print(f"🏛️ 12-AI Verdict: {pred_color} ({final_conf:.1f}%) | {consensus_tag}{v_flag} | {reason}", flush=True)

                            # Save & Dispatch ONE final decision to User DM
                            MEMORY_PREDICTIONS[next_target_period] = {
                                "color": pred_color,
                                "conf": final_conf,
                                "reason": reason,
                                "consensus": consensus_tag,
                                "violet_alert": violet_alert
                            }
                            send_user_signal(next_target_period, pred_color, final_conf, reason, consensus_tag, violet_alert)

        except Exception as e:
            print(f"[LOOP ERROR] {e}", flush=True)

        time.sleep(1.0)

if __name__ == "__main__":
    run_live_bot()
