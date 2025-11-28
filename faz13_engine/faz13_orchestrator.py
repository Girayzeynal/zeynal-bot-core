import re
import json

# =====================================================================
# 🔧 SAFE FLOAT
# =====================================================================
def _safe_float(val):
    """Harhangi bir string'i güvenli şekilde floata çevirir."""
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "."))
    except:
        return None


# =====================================================================
# 🧠 FAZ-13.2 — HYBRID PRECISION MANUAL PARSER
# =====================================================================
def normalize_manual_text(text: str, default_league: str = "NBA") -> dict:
    """
    FAZ-13.2 manuel parser — tüm ters formatlar, hatalı girişler,
    virgül noktası, takım sırası, line/odds/direction yakalama.
    GOD-LAYER için optimize edilmiştir.
    """
    raw_text = (text or "").strip()

    # Prefix temizliği
    if raw_text.startswith("/"):
        parts = raw_text.split(maxsplit=1)
        args = parts[1] if len(parts) > 1 else ""
    else:
        args = raw_text

    # Token cleanup
    args = args.replace("\n", " ").replace("\t", " ")
    raw_tokens = [t for t in args.split(" ") if t.strip()]

    tokens = []
    for t in raw_tokens:
        f = _safe_float(t)
        if f is not None:
            tokens.append(str(f))          # normalize numeric
        else:
            tokens.append(t.upper())       # normalize string

    if not tokens:
        return {
            "source": "manual",
            "raw": raw_text,
            "league": default_league,
            "home": "UNKNOWN",
            "away": "UNKNOWN",
            "market": "FT TOTAL",
            "line": None,
            "direction": None,
            "odds": None,
        }

    # League detect
    league_tags = {"NBA", "EUROLEAGUE", "EL", "BSL", "TBL"}
    league = default_league
    cleaned = []
    for t in tokens:
        if t in league_tags:
            league = t
        else:
            cleaned.append(t)
    tokens = cleaned

    # Float index tell (line/odds candidates)
    float_idx = [i for i, t in enumerate(tokens) if _safe_float(t) is not None]

    line = None
    odds = None
    direction = None

    def _norm_dir(tok):
        if tok is None:
            return None
        tok = tok.upper()
        if tok in ("U", "UNDER", "ALT"):
            return "U"
        if tok in ("O", "OVER", "ÜST", "UST"):
            return "O"
        return None

    # Line / Odds / Direction
    if float_idx:
        if len(float_idx) >= 2:
            line_pos = float_idx[-2]
            odds_pos = float_idx[-1]
            line = _safe_float(tokens[line_pos])
            odds = _safe_float(tokens[odds_pos])
        else:
            line_pos = float_idx[0]
            line = _safe_float(tokens[line_pos])

        # Direction sağ taraf
        if line_pos + 1 < len(tokens):
            direction = _norm_dir(tokens[line_pos + 1])

        # Direction sol taraf
        if direction is None and line_pos - 1 >= 0:
            direction = _norm_dir(tokens[line_pos - 1])

        first_num_idx = float_idx[0]
    else:
        first_num_idx = len(tokens)

    # Team parse
    team_tokens = tokens[:first_num_idx]

    if len(team_tokens) >= 2:
        mid = len(team_tokens) // 2
        home = " ".join(team_tokens[:mid])
        away = " ".join(team_tokens[mid:])
    elif len(team_tokens) == 1:
        home = team_tokens[0]
        away = "UNKNOWN"
    else:
        home = "UNKNOWN"
        away = "UNKNOWN"

    # Market sabit (şu an FAZ-13 total market üzerinden çalışıyor)
    market = "FT TOTAL"

    return {
        "source": "manual",
        "raw": raw_text,
        "league": league,
        "home": home,
        "away": away,
        "market": market,
        "line": line,
        "direction": direction,
        "odds": odds,
    }


# =====================================================================
# 📸 VISUAL META NORMALIZER
# =====================================================================
def normalize_visual_meta(ocr_text: str) -> dict:
    """
    Visual OCR metnini manual metaya çevirir.
    Bu fonksiyon FAZ-13.1 ile uyumludur.
    """
    if not ocr_text:
        return {
            "source": "visual",
            "raw": "",
            "league": "NBA",
            "home": "UNKNOWN",
            "away": "UNKNOWN",
            "market": "FT TOTAL",
            "line": None,
            "direction": None,
            "odds": None,
        }

    text = ocr_text.upper().replace("\n", " ")

    # HOME / AWAY tahmini (çok basit heuristik)
    words = text.split()
    if len(words) >= 2:
        home = words[0]
        away = words[1]
    else:
        home = "TEAM1"
        away = "TEAM2"

    # Line yakalama (örn: 220.5 / 167.5)
    regex = r"(\d{2,3}[.,]?\d*)"
    found_nums = re.findall(regex, text)
    line = None
    if found_nums:
        line = _safe_float(found_nums[-1])

    # U/O detect
    if "UNDER" in text or "ALT" in text or " U " in text:
        direction = "U"
    elif "OVER" in text or "UST" in text or " O " in text:
        direction = "O"
    else:
        direction = None

    return {
        "source": "visual",
        "raw": ocr_text,
        "league": "NBA",
        "home": home,
        "away": away,
        "market": "FT TOTAL",
        "line": line,
        "direction": direction,
        "odds": None,
    }


# =====================================================================
# 🧠 FAZ-13 AUTO PIPELINE (Daily, Upcoming, League, Live)
# =====================================================================
def run_faz13_auto_pipeline(source_type: str, fusion_input: dict) -> dict:
    """
    FAZ-13.1 Auto Pipeline
    (GOD-LAYER'dan önceki klasik orchestration)
    """
    return {
        "source": source_type,
        "meta": fusion_input,
        "status": "OK",
    }


# =====================================================================
# 🧾 Coupon Producers (FAZ-13.1)
# =====================================================================
def faz13_daily_coupon(data):
    return "FAZ-13 DAILY coupon burada üretilecek."

def faz13_upcoming_coupon(data):
    return "FAZ-13 UPCOMING coupon burada üretilecek."

def faz13_league_coupon(data):
    return "FAZ-13 LEAGUE coupon burada üretilecek."

def faz13_live_coupon(data):
    return "FAZ-13 LIVE coupon burada üretilecek."
