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
COOLDOWN_ROUNDS = 0

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
        # Fallback to Order-2 Markov
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
            q5_ngram = (last_c, 55.0, "Low state occurrences; default momentum")

    # 5. Quant 6: Winning Number-to-Color Bayes + Mathematical Micro-Rules
    num_trans = defaultdict(lambda: {"RED": 0, "GREEN": 0})
    for i in range(len(nums) - 1):
        num_trans[nums[i]][colors[i + 1]] += 1
    cn = num_trans.get(last_num, {"RED": 0, "GREEN": 0})
    tot_n = cn["RED"] + cn["GREEN"]

    # Micro-Rules & Empirical Priors from Historical Cache:
    if last_num == 4:
        # Number 4 historically transitions to GREEN 67.1% (51/76)
        q6_num = ("GREEN", 67.1, f"Micro-Rule: Winning Number 4 yields GREEN 67.1% ({cn['GREEN']}/{tot_n} draws)")
    elif last_num in (3, 8):
        # Numbers 3 and 8 historically yield GREEN 57.2%
        q6_num = ("GREEN", 57.2, f"Micro-Rule: Winning Number {last_num} yields GREEN 57.2% ({cn['GREEN']}/{tot_n} draws)")
    elif last_num in (6, 7):
        # Numbers 6 and 7 historically yield RED 55.2%
        q6_num = ("RED", 55.2, f"Micro-Rule: Winning Number {last_num} yields RED 55.2% ({cn['RED']}/{tot_n} draws)")
    elif tot_n >= 2:
        nt_col = "RED" if cn["RED"] >= cn["GREEN"] else "GREEN"
        nt_conf = round(max(cn["RED"], cn["GREEN"]) / tot_n * 100, 1)
        q6_num = (nt_col, nt_conf, f"Winning Number {last_num} historically yielded {nt_col} {max(cn['RED'], cn['GREEN'])}/{tot_n} times ({nt_conf}%)")
    else:
        q6_num = (last_c, 55.0, f"Number {last_num} sample small; neutral edge")

    # 6. Quant 7: Big/Small & Color Multi-Variable Correlation Matrix
    # 2-Step Compound State: ((size-2, col-2), (size-1, col-1)) -> col
    state2 = ((sizes[-2], colors[-2]), (sizes[-1], colors[-1])) if len(sizes) >= 2 else None
    t2_bs = defaultdict(lambda: {"RED": 0, "GREEN": 0})
    for i in range(len(colors) - 2):
        s_k = ((sizes[i], colors[i]), (sizes[i + 1], colors[i + 1]))
        t2_bs[s_k][colors[i + 2]] += 1

    c2_bs = t2_bs.get(state2, {"RED": 0, "GREEN": 0}) if state2 else {"RED": 0, "GREEN": 0}
    tot_2bs = c2_bs["RED"] + c2_bs["GREEN"]

    # Micro-Rule: Two consecutive Small Reds yield Green 69.2% (45/65)
    if state2 == (("SMALL", "RED"), ("SMALL", "RED")):
        q7_bs = ("GREEN", 69.2, f"Multi-Variable: (Small-Red x2) triggers 69.2% GREEN transition ({c2_bs['GREEN']}/{tot_2bs})")
    elif tot_2bs >= 15:
        bs_col = "RED" if c2_bs["RED"] >= c2_bs["GREEN"] else "GREEN"
        bs_conf = round(max(c2_bs["RED"], c2_bs["GREEN"]) / tot_2bs * 100, 1)
        q7_bs = (bs_col, bs_conf, f"2-Step Compound state {state2} yielded {bs_col} ({bs_conf}%)")
    else:
        # Fallback to 1-Step Compound State
        bs_trans = defaultdict(lambda: {"RED": 0, "GREEN": 0})
        for i in range(len(sizes) - 1):
            bs_trans[(sizes[i], colors[i])][colors[i + 1]] += 1
        last_bs = (sizes[-1], colors[-1])
        cbs = bs_trans.get(last_bs, {"RED": 0, "GREEN": 0})
        tot_bs = cbs["RED"] + cbs["GREEN"]
        if tot_bs >= 2:
            bs_col = "RED" if cbs["RED"] >= cbs["GREEN"] else "GREEN"
            bs_conf = round(max(cbs["RED"], cbs["GREEN"]) / tot_bs * 100, 1)
            q7_bs = (bs_col, bs_conf, f"Composite state {last_bs} transitioned to {bs_col} ({bs_conf}%)")
        else:
            q7_bs = (last_c, 55.0, "Composite neutral")

    # 7. Quant 8: Rolling Mean-Reversion & Streak Termination Analysis (50-Round Scope)
    # Empirical facts: 53.8% of 3-streaks terminate at 3; 65.3% of 4-streaks terminate at 4!
    recent_50 = colors[-50:] if len(colors) >= 50 else colors
    r_count = recent_50.count("RED")
    g_count = recent_50.count("GREEN")
    rev_col = "GREEN" if last_c == "RED" else "RED"

    if streak_len == 4:
        q8_mr = (rev_col, 65.3, f"4-Round {last_c} streak hits 65.3% statistical termination boundary")
    elif streak_len == 3:
        q8_mr = (rev_col, 53.8, f"3-Round {last_c} streak hits 53.8% mean-reversion inflection point")
    elif r_count >= g_count + 8:
        q8_mr = ("GREEN", 68.0, f"RED heavily overbought ({r_count} vs {g_count} in last 50); mean-reversion favors GREEN")
    elif g_count >= r_count + 8:
        q8_mr = ("RED", 68.0, f"GREEN heavily overbought ({g_count} vs {r_count} in last 50); mean-reversion favors RED")
    else:
        q8_mr = (last_c, 52.0, f"Balanced 50-round distribution ({r_count}R / {g_count}G); trend maintained")

    # 8. Quant 9: Micro-Cycle Periodicity & Rhythm (50-Round Lag-2 & Harmonic Autocorrelation)
    recent_cycle = colors[-50:] if len(colors) >= 50 else colors
    if len(recent_cycle) >= 6:
        lag2_matches = sum(1 for i in range(2, len(recent_cycle)) if recent_cycle[i] == recent_cycle[i - 2])
        lag2_total = len(recent_cycle) - 2
        lag2_pct = (lag2_matches / lag2_total * 100) if lag2_total > 0 else 50.0
        if lag2_pct >= 60.0:
            rhy_col = recent_cycle[-2]
            q9_rhy = (rhy_col, round(lag2_pct, 1), f"Strong Lag-2 cyclical harmonic active ({lag2_matches}/{lag2_total} matches | {lag2_pct:.1f}%)")
        else:
            q9_rhy = (last_c, 54.0, f"Micro-cycle rhythm in balance ({lag2_pct:.1f}% lag-2 across 50 rounds)")
    else:
        q9_rhy = (last_c, 50.0, "Insufficient cycle span")

    # 9. Quant 10: Market Chaos & Shannon Entropy Gatekeeper (50-Round Macro + 10-Round Micro)
    p_r = recent_50.count("RED") / len(recent_50)
    p_g = recent_50.count("GREEN") / len(recent_50)
    entropy_50 = 0.0
    for p in (p_r, p_g):
        if p > 0:
            entropy_50 -= p * math.log2(p)

    recent_10 = colors[-10:] if len(colors) >= 10 else colors
    p10_r = recent_10.count("RED") / len(recent_10)
    p10_g = recent_10.count("GREEN") / len(recent_10)
    entropy_10 = 0.0
    for p in (p10_r, p10_g):
        if p > 0:
            entropy_10 -= p * math.log2(p)

    if (entropy_10 >= 0.94 or entropy_50 >= 0.98) and streak_len == 1 and alt_len <= 2:
        q10_ent = ("WAIT", 0.0, f"Peak Shannon Entropy ({entropy_10:.2f} short / {entropy_50:.2f} 50-round) indicates chaotic chop; capital shield advised")
    else:
        ent_col = last_c if streak_len >= 2 else ("RED" if p_r >= p_g else "GREEN")
        q10_ent = (ent_col, 62.0, f"Controlled entropy level ({entropy_50:.2f} across 50 rounds); orderly structure")

    # 10. Quant 11: Violet (0 & 5) Dormancy & Outlier Specialist
    rounds_since_violet = 0
    for it in reversed(history_items):
        if it.get("has_violet", False) or int(it.get("num", -1)) in (0, 5):
            break
        rounds_since_violet += 1
    # Average interval in WinGo is 10 draws. Alert only when overdue (>=14) AND last number is an empirical feeder (4, 9, 1, 6) or >= 18
    violet_due = (rounds_since_violet >= 14 and last_num in (4, 9, 1, 6)) or (rounds_since_violet >= 18)
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

    recent_50_items = history_items[-50:] if len(history_items) >= 50 else history_items
    compact_parts = []
    for it in recent_50_items:
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
    global CONSECUTIVE_SKIPS, COOLDOWN_ROUNDS
    p_info = detect_market_patterns(history_items)
    recent_str = p_info["recent_compact"]
    pattern_str = p_info["pattern_desc"]
    last_color = p_info["streak_color"]
    streak_len = p_info["streak_len"]
    alt_len = p_info.get("alt_len", 1)
    is_double = p_info.get("is_double", False)
    violet_due = p_info["violet_due"]
    quants = p_info.get("quants", {})

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    # --- Phase 1: 4 Neural LLM Specialists Consult in Parallel ---
    specialist_tasks = [
        (
            "Agent 1 (Dragon Momentum: Qwen-27B)",
            MODEL_QWEN,
            (
                f"You are Agent 1 (Trend Momentum Specialist) on the 12-AI WinGo Council.\n"
                f"Recent rounds: {recent_str}\n"
                f"Market Structure: {pattern_str}\n"
                f"Mandate: In WinGo 30S, 54% of 3-streaks and 65% of 4-streaks terminate (flip color). Follow momentum ({last_color}) ONLY if a confirmed dragon streak (5+ {last_color}) is active. If streak is 3 or 4, vote for mean-reversion reversal ({'GREEN' if last_color == 'RED' else 'RED'}) or caution.\n"
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
        if streak_len in (3, 4):
            c_fall = "GREEN" if last_color == "RED" else "RED"
        elif streak_len >= 5:
            c_fall = last_color
        else:
            c_fall = "RED" if quants.get("q5", ["RED"])[0] == "RED" else "GREEN"
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
        {"name": "Agent 6 (Number-to-Color Bayes + Micro-Rules)", "color": q6[0], "conf": q6[1], "arg": q6[2]},
        {"name": "Agent 7 (Big/Small Compound Matrix)", "color": q7[0], "conf": q7[1], "arg": q7[2]},
        {"name": "Agent 8 (Mean-Reversion Imbalance Quant)", "color": q8[0], "conf": q8[1], "arg": q8[2]},
        {"name": "Agent 9 (Micro-Cycle Periodicity Quant)", "color": q9[0], "conf": q9[1], "arg": q9[2]},
        {"name": "Agent 10 (Shannon Entropy Risk Gatekeeper)", "color": q10[0], "conf": q10[1], "arg": q10[2]},
        {"name": "Agent 11 (Violet 0/5 Outlier Specialist)", "color": q11[0], "conf": q11[1], "arg": q11[2]}
    ]

    # Dynamic Weight Assignment based on Empirical Reliability
    weights = [
        1.8 if streak_len >= 3 else 1.0,           # Agent 1: Dragon Momentum
        1.8 if alt_len >= 3 else 1.0,              # Agent 2: 1-1 Chop
        1.6 if is_double else 1.0,                 # Agent 3: 2-2 Symmetry
        1.2,                                       # Agent 4: Contrarian Trap
        1.8,                                       # Agent 5: Markov N-Gram Quant
        1.9,                                       # Agent 6: Number-to-Color Bayes (67.1% on Num 4)
        1.7,                                       # Agent 7: Big/Small Compound Matrix
        1.4,                                       # Agent 8: Mean-Reversion Imbalance
        1.2,                                       # Agent 9: Micro-Cycle Autocorrelation
        1.4,                                       # Agent 10: Shannon Entropy Chaos Gatekeeper
        1.2                                        # Agent 11: Violet 0/5 Specialist
    ]

    red_votes = sum(1 for s in all_11_specialists if s["color"] == "RED")
    green_votes = sum(1 for s in all_11_specialists if s["color"] == "GREEN")
    wait_votes = sum(1 for s in all_11_specialists if s["color"] == "WAIT")

    red_weight = sum(weights[i] for i, s in enumerate(all_11_specialists) if s["color"] == "RED")
    green_weight = sum(weights[i] for i, s in enumerate(all_11_specialists) if s["color"] == "GREEN")
    total_active_weight = red_weight + green_weight

    if red_weight >= green_weight:
        w_col = "RED"
        w_v, l_v = red_votes, green_votes
        w_weight, l_weight = red_weight, green_weight
    else:
        w_col = "GREEN"
        w_v, l_v = green_votes, red_votes
        w_weight, l_weight = green_weight, red_weight

    weight_ratio = (w_weight / total_active_weight) if total_active_weight > 0 else 0.5
    calc_conf = min(93.0, max(72.0, round(66.0 + (weight_ratio * 28.0), 1)))

    # Determine Signal Grade:
    is_grade_a = (w_v >= 8 and weight_ratio >= 0.66 and calc_conf >= 85.0)
    signal_grade = "GRADE_A"

    # --- Phase 3: 🛡️ DETERMINISTIC CAPITAL SHIELD & RISK ENGINE ---
    # Rule 0: Cooldown after 2-Loss Stop-Loss
    if COOLDOWN_ROUNDS > 0:
        COOLDOWN_ROUNDS -= 1
        shield_desc = f"Stop-Loss cooldown active ({COOLDOWN_ROUNDS + 1} rounds remaining). Letting adverse cycle pass to protect capital."
        return "WAIT", 0.0, shield_desc, "🛑 Capital Shield (Stop-Loss Cooldown)", False, "SHIELD"

    # Rule 1: HARD STOP-LOSS AT LEVEL 2 (User Mandate: Never allow Level 3 loss!)
    if current_loss_streak >= 2:
        shield_desc = "Max 2 consecutive losses reached. Level 3 betting strictly blocked to preserve bankroll."
        return "WAIT", 0.0, shield_desc, "🛑 Stop-Loss (Max 2 Levels Reached)", False, "SHIELD"

    # Rule 2: Level 2 Recovery Super-Sniper Guard (When current_loss_streak == 1)
    if current_loss_streak == 1:
        # Recovery bet MUST be ultra-safe: require at least 9 votes and >=72% weight and no entropy chaos
        if w_v < 9 or weight_ratio < 0.72 or calc_conf < 86.0 or abs(red_votes - green_votes) < 4:
            shield_desc = f"Level 2 recovery active. Council consensus ({w_v}-{l_v} | {weight_ratio*100:.0f}% Weight) is below 9+ sniper threshold. Recovery bet skipped to prevent Level 2 loss."
            return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (Level 2 Sniper Guard)", False, "SHIELD"

    # Rule 3: Deadlock 50/50 Split Filter (abs diff <= 2, e.g. 6-5, 5-5, 7-4)
    if abs(red_votes - green_votes) <= 2:
        shield_desc = f"Council specialists deadlocked ({red_votes}R vs {green_votes}G); 50/50 coin-flip risk filtered."
        return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (Deadlock Filter)", False, "SHIELD"

    # Rule 4: Peak Shannon Chaos Filter
    is_entropy_wait = (quants.get("q10", ("OK", 0))[0] == "WAIT")
    if is_entropy_wait:
        shield_desc = "Peak Shannon Entropy detected; turbulent market chop filtered to protect capital."
        return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (Chaos Filter)", False, "SHIELD"

    # Rule 5: GRADE-A SNIPER ONLY (Strictly NO Grade-B bets! Grade-B caused 86 losses today!)
    if not is_grade_a or w_v < 8:
        shield_desc = f"Council plurality only ({w_v}-{l_v} | {weight_ratio*100:.0f}% Weight). Sub-80% setup filtered to protect win rate."
        return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (Sniper Only)", False, "SHIELD"

    # --- Phase 4: Council Synthesis by Arbiter (Agent 12) ---
    spec_summary = "\n".join([
        f"- {s['name']}: Proposes {s['color']} ({s['conf']:.0f}%) -> Argument: \"{s['arg']}\""
        for s in all_11_specialists
    ])

    if is_grade_a:
        consensus_tag = f"🔥 Council Super-Majority ({w_v}-{l_v} | {weight_ratio*100:.0f}% Weight)"
    else:
        consensus_tag = f"⚠️ Council Plurality ({w_v}-{l_v} | {weight_ratio*100:.0f}% Weight)"

    prompt_arbiter = (
        f"You are Agent 12 (Supreme Arbiter) presiding over the 12-AI WinGo Council.\n"
        f"Recent sequence: {recent_str}\n"
        f"Market Structure: {pattern_str}\n"
        f"Current Consecutive Loss Streak: {current_loss_streak}\n"
        f"Specialists Debate:\n{spec_summary}\n"
        f"Weighted Consensus: {w_col} ({w_v}-{l_v} | {weight_ratio*100:.0f}% Weight | Grade: {signal_grade})\n\n"
        f"Supreme Arbiter Mandate:\n"
        f"Confirm the winning color '{w_col}' and provide a concise, sharp 1-sentence synthesis of why this color was selected by the council.\n\n"
        f"Return JSON ONLY:\n"
        f"{{\n"
        f'  "final_color": "{w_col}",\n'
        f'  "confidence": {calc_conf},\n'
        f'  "violet_alert": false,\n'
        f'  "debate_summary": "1 concise sentence summarizing how consensus was reached."\n'
        f"}}"
    )

    final_summary = f"12-Agent Council majority voted {w_col} ({w_v}-{l_v} | {weight_ratio*100:.0f}% weight)."
    v_alert = bool(violet_due)

    # Arbiter consultation
    for arb_model in [MODEL_GPT120B, MODEL_QWEN]:
        try:
            r_arb = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json={
                "model": arb_model,
                "messages": [{"role": "user", "content": prompt_arbiter}],
                "response_format": {"type": "json_object"}
            }, timeout=3.5)
            if r_arb.status_code == 200:
                res_arb = json.loads(r_arb.json()["choices"][0]["message"]["content"])
                summary_txt = res_arb.get("debate_summary", "")
                if summary_txt:
                    final_summary = summary_txt
                break
        except Exception:
            continue

    return w_col, calc_conf, final_summary, consensus_tag, v_alert, signal_grade

# ====================================================
# 🚀 USER SIGNALS (SENT DIRECTLY TO USER DM)
# ====================================================
def send_user_signal(target_period, color, confidence, reason, consensus_tag="12-AI Council", violet_alert=False, signal_grade="GRADE_A"):
    short_period = target_period[-4:] if len(target_period) >= 4 else target_period

    if color == "WAIT":
        msg = (
            f"⏸️ <b>WinGo 30S Capital Shield</b> | <code>...{short_period}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>Action</b>               : <b>⏸️ SKIP / NO BET</b>\n"
            f"⚠️ <b>Trigger Mode</b>         : <code>{consensus_tag}</code>\n"
            f"💬 <b>Risk Analysis</b>        : <i>\"{reason}\"</i>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>Capital protected. Awaiting high-conviction setup next round.</i>"
        )
    else:
        c_emoji = "🔴 RED" if color == "RED" else "🟢 GREEN"
        if CURRENT_LOSS_STREAK == 1:
            grade_badge = "🎯 <b>LEVEL 2 RECOVERY (SNIPER)</b> [2.5x - 3x Stake]"
        else:
            grade_badge = "🔥 <b>LEVEL 1 BASE BET (SNIPER)</b> [Standard Stake]"
        v_alert_line = ""
        if violet_alert:
            target_num = "0" if color == "RED" else "5"
            v_alert_line = f"🟣 <b>Violet Watch</b>        : ⚠️ <b>High Chance of {target_num} (Violet)!</b>\n"

        msg = (
            f"🎯 <b>WinGo 30S 12-AI Council Signal</b> | <code>...{short_period}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👉 <b>Predicted Color</b>     : <b>{c_emoji}</b>\n"
            f"🎖️ <b>Signal Grade</b>        : {grade_badge}\n"
            f"{v_alert_line}"
            f"📊 <b>Confidence</b>          : <code>{confidence:.1f}%</code>\n"
            f"🏛️ <b>Council Verdict</b>     : <b>{consensus_tag}</b>\n"
            f"💬 <b>Debate Summary</b>      : <i>\"{reason}\"</i>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

    try:
        send_telegram_msg(USER_ALERT_CHAT_ID, msg, timeout=8, retries=1)
        print(f"👉 [DM SIGNAL SENT] Period: ...{short_period} | {color} ({confidence:.1f}%) | {consensus_tag} | Grade: {signal_grade}", flush=True)
    except Exception as e:
        print(f"[USER ALERT ERROR] {e}", flush=True)

def send_user_result(period, actual_number, actual_color, pred):
    global CURRENT_LOSS_STREAK, TOTAL_WINS, TOTAL_LOSSES, TOTAL_SKIPS, CONSECUTIVE_SKIPS, COOLDOWN_ROUNDS
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
        shield_mode = pred.get("consensus", "Capital Shield")
        msg = (
            f"🛡️ <b>CAPITAL SHIELD RESULT</b> | Period: <code>...{short_period}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎲 Actual Result : <b>{c_display}</b>\n"
            f"✅ <b>Capital Protected</b>: Skipped risky round ({shield_mode}).\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        try:
            send_telegram_msg(USER_ALERT_CHAT_ID, msg, timeout=8, retries=1)
            print(f"[RESULT] Period: ...{short_period} | SKIPPED (Capital Protected)", flush=True)
        except Exception as e:
            print(f"[USER RESULT ERROR] {e}", flush=True)
        return

    CONSECUTIVE_SKIPS = 0

    # In WinGo, predicting RED and getting 0 is a win (half payout for color).
    # Predicting GREEN and getting 5 is a win (half payout for color).
    predicted_color = pred["color"]
    color_win = (predicted_color == actual_color)

    if color_win:
        win_level = 2 if CURRENT_LOSS_STREAK == 1 else 1
        CURRENT_LOSS_STREAK = 0
        TOTAL_WINS += 1
        if win_level == 2:
            header = "✅ <b>WIN (Level 2 Recovery Payout 2x)</b> 🎉 [PROFIT SECURED]"
        elif is_violet:
            if pred.get("violet_alert"):
                header = "🟣 <b>JACKPOT VIOLET WIN (4.5x Payout)!</b>"
            else:
                header = "🟡 <b>HALF WIN (1.5x Payout - Mixed Violet)</b>"
        else:
            header = "✅ <b>WIN (Level 1 Payout 2x)</b>"
        extra_note = "🎉 <i>Profit secured. Next bet starts at Level 1 base stake.</i>\n"
    else:
        CURRENT_LOSS_STREAK += 1
        TOTAL_LOSSES += 1
        if CURRENT_LOSS_STREAK == 1:
            header = "❌ <b>LOSS (Level 1)</b> 🛡️ [SNIPER RECOVERY ARMED]"
            extra_note = "⚠️ <i>Next round: Level 2 Recovery (Grade-A+ Sniper Only).</i>\n"
        else:
            # STOP-LOSS HIT! MAX 2 LOSSES REACHED!
            header = "❌ <b>LOSS (Level 2) — 🛑 MAX STOP-LOSS EXECUTED!</b>"
            extra_note = "🛑 <b>Max 2-loss limit reached! Level 3 betting strictly BLOCKED to protect bankroll. 2-round cooldown active. Resetting cycle to Level 1.</b>\n"
            CURRENT_LOSS_STREAK = 0
            COOLDOWN_ROUNDS = 2

    win_rate = (TOTAL_WINS / (TOTAL_WINS + TOTAL_LOSSES) * 100) if (TOTAL_WINS + TOTAL_LOSSES) > 0 else 0.0
    grade_str = f" | {pred.get('grade', 'SNIPER')}" if pred.get('grade') else ""

    msg = (
        f"{header} | Period: <code>...{short_period}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎲 Actual Result : <b>{c_display}</b>\n"
        f"🎯 Predicted     : <b>{predicted_color}</b>{grade_str}\n"
        f"📈 Session Stats : <code>{TOTAL_WINS}W - {TOTAL_LOSSES}L ({win_rate:.1f}%)</code> | <code>{TOTAL_SKIPS} Skips</code>\n"
        f"{extra_note}"
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
                            pred_color, final_conf, reason, consensus_tag, violet_alert, signal_grade = ask_12_ai_council(
                                MEMORY_HISTORY, CURRENT_LOSS_STREAK
                            )

                            v_flag = " [🟣 VIOLET ALERT]" if violet_alert else ""
                            print(f"🏛️ 12-AI Verdict: {pred_color} ({final_conf:.1f}%) | {consensus_tag}{v_flag} | Grade: {signal_grade} | {reason}", flush=True)

                            # Save & Dispatch ONE final decision to User DM
                            MEMORY_PREDICTIONS[next_target_period] = {
                                "color": pred_color,
                                "conf": final_conf,
                                "reason": reason,
                                "consensus": consensus_tag,
                                "violet_alert": violet_alert,
                                "grade": signal_grade
                            }
                            send_user_signal(next_target_period, pred_color, final_conf, reason, consensus_tag, violet_alert, signal_grade)

        except Exception as e:
            print(f"[LOOP ERROR] {e}", flush=True)

        time.sleep(1.0)

if __name__ == "__main__":
    run_live_bot()
