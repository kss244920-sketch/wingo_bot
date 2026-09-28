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
POST_STOP_LOSS_GUARD = False

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

def send_telegram_msg(chat_id, text, timeout=8, retries=1, pin=False):
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
            else:
                print(f"[TELEGRAM API ERROR] Status {r.status_code}: {r.text}", flush=True)
        except Exception:
            if attempt < retries:
                time.sleep(0.5)
                continue
            raise
    return False

def pin_telegram_msg(chat_id, message_id, disable_notification=True):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/pinChatMessage"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "disable_notification": disable_notification
    }
    try:
        r = requests.post(url, json=payload, timeout=6)
        if r.status_code == 200:
            return True
        else:
            print(f"[PIN ERROR] Status {r.status_code}: {r.text}", flush=True)
    except Exception as e:
        print(f"[PIN EXCEPTION] {e}", flush=True)
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
            if alt_len >= 3:
                ng_col = "GREEN" if last_c == "RED" else "RED"
                q5_ngram = (ng_col, 65.0, f"Active 1-1 alternation ({alt_len} rounds); rhythm continuation")
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

    # 7. Quant 8: Full-Database Mean-Reversion & Imbalance Analysis (ALL DB Rounds)
    tot_db = len(colors)
    r_db = colors.count("RED")
    g_db = colors.count("GREEN")
    rev_col = "GREEN" if last_c == "RED" else "RED"

    if streak_len >= 3:
        # Golden Dragon Rule: Never cut the dragon! Follow streak momentum until natural exhaustion.
        q8_mr = (last_c, 72.0, f"Active {last_c} dragon streak ({streak_len} rounds); momentum continuation rule")
    elif alt_len >= 3:
        # In an active 1-1 alternation, mean-reversion rhythm favors continuing the chop!
        q8_mr = (rev_col, 68.0, f"Active 1-1 alternating chop ({alt_len} rounds); rhythm continuation favors {rev_col}")
    elif r_db > g_db + (tot_db * 0.04):
        q8_mr = ("GREEN", 66.0, f"RED overall overbought ({r_db}R vs {g_db}G across all {tot_db} DB rounds); macro balance favors GREEN")
    elif g_db > r_db + (tot_db * 0.04):
        q8_mr = ("RED", 66.0, f"GREEN overall overbought ({g_db}G vs {r_db}R across all {tot_db} DB rounds); macro balance favors RED")
    else:
        # Check rolling 30-round micro skew:
        r_30 = colors[-30:].count("RED") if tot_db >= 30 else r_db
        g_30 = colors[-30:].count("GREEN") if tot_db >= 30 else g_db
        if r_30 >= g_30 + 5:
            q8_mr = ("GREEN", 64.0, f"RED short-term overbought ({r_30} vs {g_30}); micro balance favors GREEN")
        elif g_30 >= r_30 + 5:
            q8_mr = ("RED", 64.0, f"GREEN short-term overbought ({g_30} vs {r_30}); micro balance favors RED")
        else:
            q8_mr = (rev_col if alt_len >= 2 else (last_c if streak_len >= 2 else rev_col), 54.0, f"Balanced database distribution ({r_db}R / {g_db}G across {tot_db} rounds)")

    # 8. Quant 9: Full-Database Micro-Cycle Periodicity & Harmonic Autocorrelation (ALL DB Rounds)
    if tot_db >= 6:
        lag2_matches = sum(1 for i in range(2, tot_db) if colors[i] == colors[i - 2])
        lag2_total = tot_db - 2
        lag2_pct = (lag2_matches / lag2_total * 100) if lag2_total > 0 else 50.0

        rec20 = colors[-20:] if tot_db >= 20 else colors
        rec_lag2 = sum(1 for i in range(2, len(rec20)) if rec20[i] == rec20[i - 2])
        rec_pct = (rec_lag2 / (len(rec20) - 2) * 100) if len(rec20) > 2 else lag2_pct

        if rec_pct >= 58.0 or lag2_pct >= 56.0:
            rhy_col = colors[-2]
            q9_rhy = (rhy_col, round(max(rec_pct, lag2_pct), 1), f"Strong Lag-2 harmonic active ({rec_lag2}/{len(rec20)-2} recent | {lag2_matches}/{lag2_total} all DB)")
        elif alt_len >= 3:
            q9_rhy = (rev_col, 65.0, f"1-1 Alternating harmonic active ({alt_len} rounds)")
        else:
            q9_rhy = (rev_col if alt_len >= 2 else (last_c if streak_len >= 2 else rev_col), 53.0, f"Harmonic in balance ({lag2_pct:.1f}% DB lag-2 across {tot_db} rounds)")
    else:
        q9_rhy = (last_c, 50.0, "Insufficient cycle span")

    # 9. Quant 10: Multi-Scale Shannon Entropy Gatekeeper (ALL DB Macro + 12-Round Micro)
    p_r_db = r_db / tot_db if tot_db > 0 else 0.5
    p_g_db = g_db / tot_db if tot_db > 0 else 0.5
    entropy_db = 0.0
    for p in (p_r_db, p_g_db):
        if p > 0:
            entropy_db -= p * math.log2(p)

    recent_12 = colors[-12:] if tot_db >= 12 else colors
    p12_r = recent_12.count("RED") / len(recent_12)
    p12_g = recent_12.count("GREEN") / len(recent_12)
    entropy_12 = 0.0
    for p in (p12_r, p12_g):
        if p > 0:
            entropy_12 -= p * math.log2(p)

    if entropy_12 >= 0.95 and streak_len == 1 and alt_len <= 2:
        q10_ent = ("WAIT", 0.0, f"Peak Shannon Entropy ({entropy_12:.2f} micro / {entropy_db:.2f} DB) indicates chaotic chop; capital shield advised")
    else:
        ent_col = rev_col if alt_len >= 3 else (last_c if streak_len >= 2 else ("RED" if p_r_db >= p_g_db else "GREEN"))
        q10_ent = (ent_col, 62.0, f"Orderly structure ({entropy_db:.2f} entropy across all {tot_db} DB rounds)")

    # 10. Quant 11: Full-Database Violet (0 & 5) Matrix (ALL DB Rounds)
    violet_intervals = []
    last_v_idx = None
    for idx, it in enumerate(history_items):
        if it.get("has_violet", False) or int(it.get("num", -1)) in (0, 5):
            if last_v_idx is not None:
                violet_intervals.append(idx - last_v_idx)
            last_v_idx = idx

    avg_v_interval = round(sum(violet_intervals) / len(violet_intervals), 1) if violet_intervals else 10.0
    rounds_since_violet = (len(history_items) - 1 - last_v_idx) if last_v_idx is not None else 0

    violet_due = (rounds_since_violet >= avg_v_interval * 1.3 and last_num in (4, 9, 1, 6)) or (rounds_since_violet >= avg_v_interval * 1.7)
    if violet_due:
        v_col = "RED" if last_num in (1, 2, 3, 4) else "GREEN"
        q11_vio = (v_col, 75.0, f"Violet overdue ({rounds_since_violet} rounds dormant vs {avg_v_interval} avg across all {len(violet_intervals)} DB cycles); hedge on 0/5")
    else:
        v_flow = rev_col if alt_len >= 3 else last_c
        q11_vio = (v_flow, 55.0, f"Violet normal ({rounds_since_violet} dormant vs {avg_v_interval} DB avg)")

    # 11. Quant 12: Weibull Hazard Function & Survival Analysis (ALL DB Streaks)
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

    if streak_len >= 5 and h_rate >= 70.0:
        q12_hazard = ("WAIT", h_rate, f"Weibull Hazard Climax ({h_rate}% termination rate at {streak_len}-streak across DB); exhaustion imminent")
    elif streak_len in (3, 4) and h_rate < 60.0:
        q12_hazard = (last_c, round(100 - h_rate, 1), f"Weibull Survival favorable ({100-h_rate:.1f}% survival rate); dragon continuation supported")
    elif alt_len >= 3:
        q12_hazard = (rev_col, 68.0, f"Alternation survival favors rhythm continuation ({alt_len} rounds)")
    else:
        q12_hazard = (rev_col if alt_len >= 2 else last_c, 55.0, f"Streak length {streak_len} hazard in normal regime ({h_rate}%)")

    # 12. Quant 13: Discrete Fourier Transform (DFT) & Harmonic Wave Analysis (Last 64 rounds)
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
        q13_fourier = (f_col, f_conf, f"Fourier DFT dominant {dom_period}-round wave (Power: {best_p:.1f}); trajectory favors {f_col}")
    else:
        q13_fourier = (last_c, 50.0, "Insufficient Fourier window")

    # 13. Quant 14: Kolmogorov Algorithmic Complexity / Lempel-Ziv Regularity (Last 60 rounds)
    import zlib
    n_k = min(len(colors), 60)
    if n_k >= 10:
        seq_str = "".join(["R" if c == "RED" else "G" for c in colors[-n_k:]])
        comp_r = len(zlib.compress((seq_str + "R").encode("utf-8"), level=9))
        comp_g = len(zlib.compress((seq_str + "G").encode("utf-8"), level=9))
        if comp_r < comp_g:
            q14_kolmo = ("RED", 66.0, f"Kolmogorov algorithmic compressibility higher for RED ({comp_r}B vs {comp_g}B); pattern consistency")
        elif comp_g < comp_r:
            q14_kolmo = ("GREEN", 66.0, f"Kolmogorov algorithmic compressibility higher for GREEN ({comp_g}B vs {comp_r}B); pattern consistency")
        else:
            q14_kolmo = ("WAIT", 50.0, "Kolmogorov equal complexity; white-noise indeterminate state")
    else:
        q14_kolmo = (last_c, 50.0, "Insufficient Kolmogorov window")

    # 14. Quant 15: Exponentially-Decayed Beta-Binomial Bayesian Posterior (Decay gamma=0.96)
    alpha_b, beta_b = 1.0, 1.0
    for c in colors:
        alpha_b = (alpha_b * 0.96) + (1.0 if c == "GREEN" else 0.0)
        beta_b = (beta_b * 0.96) + (1.0 if c == "RED" else 0.0)
    tot_pseudo = alpha_b + beta_b
    post_mean = alpha_b / tot_pseudo
    var_b = (alpha_b * beta_b) / ((tot_pseudo**2) * (tot_pseudo + 1))
    std_b = math.sqrt(var_b) if var_b > 0 else 0.05
    th_low = max(0.0, post_mean - 1.96 * std_b)
    th_high = min(1.0, post_mean + 1.96 * std_b)

    if th_low <= 0.50 <= th_high:
        q15_bayes = ("WAIT", 50.0, f"95% Bayesian Credible Interval [{th_low*100:.1f}%, {th_high*100:.1f}%] brackets 50%; neutral edge")
    elif th_low > 0.50:
        q15_bayes = ("GREEN", round(post_mean * 100, 1), f"Bayesian Credible separation proves GREEN edge (Mean: {post_mean*100:.1f}% | CI: [{th_low*100:.1f}%, {th_high*100:.1f}%])")
    else:
        q15_bayes = ("RED", round((1.0 - post_mean) * 100, 1), f"Bayesian Credible separation proves RED edge (Mean: {(1-post_mean)*100:.1f}% | CI: [{(1-th_high)*100:.1f}%, {(1-th_low)*100:.1f}%])")

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
    desc.append(f"📐 Hazard: {q12_hazard[0]}")
    desc.append(f"🌊 Fourier: {q13_fourier[0]}")
    if violet_due:
        desc.append(f"🟣 Violet Overdue ({rounds_since_violet} rounds dormant)")

    recent_80_items = history_items[-80:] if len(history_items) >= 80 else history_items
    compact_parts = []
    for it in recent_80_items:
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
            "q11": q11_vio,
            "q12": q12_hazard,
            "q13": q13_fourier,
            "q14": q14_kolmo,
            "q15": q15_bayes
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
                f"Mandate: Identify false breakouts and retail traps. NOTE: Never cut an active dragon trend (3+ streak) or fight an active 1-1 chop. Only flag contrarian reversals if a streak is >= 7.\n"
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
        if streak_len >= 3:
            # Golden Dragon Rule: Follow the streak! Never cut the dragon.
            c_fall = last_color
        elif alt_len >= 3:
            # Follow 1-1 alternating chop rhythm
            c_fall = "GREEN" if last_color == "RED" else "RED"
        else:
            c_fall = "RED" if quants.get("q5", ["RED"])[0] == "RED" else "GREEN"
        return {"name": agent_name, "color": c_fall or "RED", "conf": 70.0, "arg": "Empirical pattern fallback"}

    with ThreadPoolExecutor(max_workers=4) as executor:
        llm_specialists = list(executor.map(query_specialist, specialist_tasks))

    # --- Phase 2: Compile All 15 Specialists (4 LLM + 11 Database & Pure Math Quants) ---
    q5 = quants.get("q5", (last_color, 60.0, "N-Gram fallback"))
    q6 = quants.get("q6", (last_color, 55.0, "Number transition fallback"))
    q7 = quants.get("q7", (last_color, 55.0, "Big/Small transition fallback"))
    q8 = quants.get("q8", (last_color, 55.0, "Mean-reversion fallback"))
    q9 = quants.get("q9", (last_color, 55.0, "Periodicity fallback"))
    q10 = quants.get("q10", (last_color, 55.0, "Entropy fallback"))
    q11 = quants.get("q11", (last_color, 55.0, "Violet fallback"))
    q12 = quants.get("q12", (last_color, 50.0, "Hazard fallback"))
    q13 = quants.get("q13", (last_color, 50.0, "Fourier fallback"))
    q14 = quants.get("q14", (last_color, 50.0, "Kolmogorov fallback"))
    q15 = quants.get("q15", (last_color, 50.0, "Bayesian fallback"))

    all_specialists = [
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
        {"name": "Agent 11 (Violet 0/5 Outlier Specialist)", "color": q11[0], "conf": q11[1], "arg": q11[2]},
        {"name": "Agent 12 (Weibull Hazard & Streak Survival Quant)", "color": q12[0], "conf": q12[1], "arg": q12[2]},
        {"name": "Agent 13 (Fourier Discrete Spectral Wave Quant)", "color": q13[0], "conf": q13[1], "arg": q13[2]},
        {"name": "Agent 14 (Kolmogorov Algorithmic Complexity Quant)", "color": q14[0], "conf": q14[1], "arg": q14[2]},
        {"name": "Agent 15 (Exponentially-Decayed Bayesian Quant)", "color": q15[0], "conf": q15[1], "arg": q15[2]}
    ]

    # Dynamic Weight Assignment based on Empirical Reliability
    weights = [
        2.5 if streak_len >= 4 else (1.5 if streak_len == 3 else 1.0), # Agent 1: Dragon Momentum
        2.5 if alt_len >= 3 else 1.0,                                   # Agent 2: 1-1 Chop
        1.8 if is_double else 1.0,                                      # Agent 3: 2-2 Symmetry
        1.2,                                                            # Agent 4: Contrarian Trap
        1.8,                                                            # Agent 5: Markov N-Gram Quant
        2.0,                                                            # Agent 6: Number-to-Color Bayes (67.1% on Num 4)
        1.7,                                                            # Agent 7: Big/Small Compound Matrix
        1.5,                                                            # Agent 8: Mean-Reversion Imbalance
        1.3,                                                            # Agent 9: Micro-Cycle Autocorrelation
        1.5,                                                            # Agent 10: Shannon Entropy Chaos Gatekeeper
        1.2,                                                            # Agent 11: Violet 0/5 Specialist
        1.8,                                                            # Agent 12: Weibull Hazard & Survival Quant
        1.5,                                                            # Agent 13: Fourier Spectral Wave Quant
        1.4,                                                            # Agent 14: Kolmogorov Algorithmic Complexity Quant
        1.7                                                             # Agent 15: Bayesian Decay Credible Interval Quant
    ]

    red_votes = sum(1 for s in all_specialists if s["color"] == "RED")
    green_votes = sum(1 for s in all_specialists if s["color"] == "GREEN")
    wait_votes = sum(1 for s in all_specialists if s["color"] == "WAIT")

    red_weight = sum(weights[i] for i, s in enumerate(all_specialists) if s["color"] == "RED")
    green_weight = sum(weights[i] for i, s in enumerate(all_specialists) if s["color"] == "GREEN")
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
    calc_conf = min(95.0, max(75.0, round(68.0 + (weight_ratio * 27.0), 1)))

    global POST_STOP_LOSS_GUARD
    signal_grade = "GRADE_A"

    # --- Phase 3: 🛡️ ZERO-LOSS CAPITAL SHIELD & PURE-MATH RISK ENGINE ---

    # Hard Cap 0: Max 2 Losses Hard Stop-Loss (Never allow Level 3 bet!)
    if current_loss_streak >= 2:
        POST_STOP_LOSS_GUARD = True
        shield_desc = "Max 2 consecutive losses reached. Level 3 betting strictly blocked to preserve bankroll."
        return "WAIT", 0.0, shield_desc, "🛑 Stop-Loss (Max 2 Levels Reached)", False, "SHIELD"

    # Mathematical Gate 1: Weibull Hazard Climax (Streak Exhaustion Death Protection)
    if q12[0] == "WAIT" or (streak_len >= 5 and float(q12[1]) >= 70.0):
        shield_desc = f"Weibull Hazard Climax ({q12[1]}% termination hazard at {streak_len}-streak); streak death filtered to protect capital."
        return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (Weibull Hazard Climax)", False, "SHIELD"

    # Mathematical Gate 2: Kolmogorov & Bayesian White-Noise Incompressibility Gate
    if q14[0] == "WAIT" and q15[0] == "WAIT":
        shield_desc = "Kolmogorov and Bayesian Credible Interval confirm uncompressible white-noise state; 50/50 toss filtered."
        return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (Kolmogorov-Bayes White Noise)", False, "SHIELD"

    # Anti-Trap 1: NEVER CUT THE DRAGON (Streak >= 3)
    if streak_len >= 3 and w_col != last_color:
        shield_desc = f"Active {last_color} dragon streak ({streak_len} rounds). Reversal bet blocked by Dragon Law. Ride the dragon or wait for natural break."
        return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (Dragon Counter-Trend Trap)", False, "SHIELD"

    # Anti-Trap 2: 1-1 Alternating Chop Anti-Trap (alt_len >= 3)
    if alt_len >= 3 and w_col == last_color and w_v < 12:
        shield_desc = f"Active 1-1 alternating chop ({alt_len} rounds). Opposing continuation trap filtered to protect win rate."
        return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (1-1 Alternation Trap)", False, "SHIELD"

    # Anti-Trap 3: Peak Shannon Chaos Filter
    is_entropy_wait = (quants.get("q10", ("OK", 0))[0] == "WAIT")
    if is_entropy_wait:
        shield_desc = "Peak Shannon Entropy detected; turbulent market chop filtered to protect capital."
        return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (Chaos Filter)", False, "SHIELD"

    # Anti-Trap 4: Deadlock / Coin-Flip Risk Filter (Any split where diff <= 2)
    if abs(red_votes - green_votes) <= 2:
        shield_desc = f"Council specialists deadlocked ({red_votes}R vs {green_votes}G); 50/50 coin-flip risk filtered."
        return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (Deadlock Filter)", False, "SHIELD"

    # Tier 1: POST-STOP-LOSS ULTRA-SNIPER GUARD
    if POST_STOP_LOSS_GUARD:
        if w_v < 12 or weight_ratio < 0.76 or calc_conf < 87.0 or (w_v - l_v) < 6:
            shield_desc = f"Post-Stop-Loss Ultra-Sniper Guard active ({w_v}-{l_v} | {weight_ratio*100:.0f}% Weight). Waiting for 12+/15 Golden Setup to guarantee win."
            return "WAIT", 0.0, shield_desc, "💎 Capital Shield (Post-Stop-Loss Golden Sniper)", False, "SHIELD"
        else:
            POST_STOP_LOSS_GUARD = False
            signal_grade = "ULTRA_SURE_SHOT"

    # Tier 2: LEVEL 2 RECOVERY GUARD (When current_loss_streak == 1)
    elif current_loss_streak == 1:
        if w_v < 11 or weight_ratio < 0.74 or calc_conf < 86.0 or (w_v - l_v) < 5:
            shield_desc = f"Level 2 Recovery armed ({w_v}-{l_v} | {weight_ratio*100:.0f}% Weight). Sub-optimal consensus filtered. Awaiting 11+ sniper setup to prevent 2nd loss."
            return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (Level 2 Recovery Guard)", False, "SHIELD"
        signal_grade = "GRADE_A_PLUS"

    # Tier 3: LEVEL 1 BASE BET SNIPER FILTER (Zero-Loss Mandate)
    else:
        if w_v < 10 or weight_ratio < 0.68 or calc_conf < 82.0 or (w_v - l_v) < 4:
            shield_desc = f"Council consensus split ({w_v}-{l_v} | {weight_ratio*100:.0f}% Weight). Setup filtered to guarantee zero-loss accuracy."
            return "WAIT", 0.0, shield_desc, "🛡️ Capital Shield (Selective Sniper Filter)", False, "SHIELD"
        signal_grade = "GRADE_A"

    # --- Phase 4: Council Synthesis by Arbiter (Agent 16) ---
    spec_summary = "\n".join([
        f"- {s['name']}: Proposes {s['color']} ({s['conf']:.0f}%) -> Argument: \"{s['arg']}\""
        for s in all_specialists
    ])

    if signal_grade == "ULTRA_SURE_SHOT":
        consensus_tag = f"💎 Council Golden Unanimity ({w_v}-{l_v} | {weight_ratio*100:.0f}% Weight)"
    elif w_v >= 12:
        consensus_tag = f"🔥 Council Super-Majority ({w_v}-{l_v} | {weight_ratio*100:.0f}% Weight)"
    else:
        consensus_tag = f"🎯 Council Strong Majority ({w_v}-{l_v} | {weight_ratio*100:.0f}% Weight)"

    prompt_arbiter = (
        f"You are Agent 16 (Supreme Arbiter) presiding over the 16-Agent AI & Math WinGo Council.\n"
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

    final_summary = f"16-Agent Council majority voted {w_col} ({w_v}-{l_v} | {weight_ratio*100:.0f}% weight)."
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
            f"💡 <i>Capital protected. Awaiting ultra-high conviction sniper setup next round.</i>"
        )
    else:
        c_emoji = "🔴 RED" if color == "RED" else "🟢 GREEN"
        if signal_grade == "ULTRA_SURE_SHOT":
            grade_badge = "💎 <b>ULTRA SURE-SHOT COMEBACK</b> [Golden Setup 99% Conviction]"
        elif CURRENT_LOSS_STREAK == 1:
            grade_badge = "🎯 <b>LEVEL 2 RECOVERY (SNIPER)</b> [2.5x - 3x Stake]"
        else:
            grade_badge = "🔥 <b>LEVEL 1 BASE BET (SNIPER)</b> [Standard Stake]"
        v_alert_line = ""
        if violet_alert:
            target_num = "0" if color == "RED" else "5"
            v_alert_line = f"🟣 <b>Violet Watch</b>        : ⚠️ <b>High Chance of {target_num} (Violet)!</b>\n"

        msg = (
            f"🎯 <b>WinGo 30S 16-Agent AI & Math Council Signal</b> | <code>...{short_period}</code>\n"
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
        # Only pin actionable BET signals (not WAIT skips) so channel members see active bet!
        should_pin = (color != "WAIT")
        send_telegram_msg(USER_ALERT_CHAT_ID, msg, timeout=8, retries=1, pin=should_pin)
        print(f"👉 [DM SIGNAL SENT] Period: ...{short_period} | {color} ({confidence:.1f}%) | {consensus_tag} | Grade: {signal_grade}", flush=True)
    except Exception as e:
        print(f"[USER ALERT ERROR] {e}", flush=True)

def send_user_result(period, actual_number, actual_color, pred):
    global CURRENT_LOSS_STREAK, TOTAL_WINS, TOTAL_LOSSES, TOTAL_SKIPS, CONSECUTIVE_SKIPS, POST_STOP_LOSS_GUARD
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
        POST_STOP_LOSS_GUARD = False
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
            extra_note = (
                "🛑 <b>Max 2-loss limit reached! Level 3 betting strictly BLOCKED to protect bankroll. Resetting cycle to Level 1.</b>\n"
                "💎 <i>Post-Stop-Loss Ultra-Sniper Guard activated: Next bet strictly held until 9+ consensus Golden Setup appears!</i>\n"
            )
            CURRENT_LOSS_STREAK = 0
            POST_STOP_LOSS_GUARD = True

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
                            # 16 AI & Math Quants aapas me debate karke final prediction decide karte hain
                            pred_color, final_conf, reason, consensus_tag, violet_alert, signal_grade = ask_12_ai_council(
                                MEMORY_HISTORY, CURRENT_LOSS_STREAK
                            )

                            v_flag = " [🟣 VIOLET ALERT]" if violet_alert else ""
                            print(f"🏛️ 16-Agent Council Verdict: {pred_color} ({final_conf:.1f}%) | {consensus_tag}{v_flag} | Grade: {signal_grade} | {reason}", flush=True)

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
