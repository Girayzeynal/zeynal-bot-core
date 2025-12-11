# ============================================================
#   FAZ-13 ORCHESTRATOR — HYBRID BASELINE ENGINE EDITION
#   FULL REWRITE — 2025-12
# ============================================================

import statistics

# ============================================================
#   H Y B R I D   B A S E L I N E   E N G I N E
# ============================================================

LEAGUE_BASELINES = {
    "NBA": 230.0,
    "EUROCUP": 162.0,
    "EUROLEAGUE": 155.0,
    "FIBA": 150.0,
}

FAMILY_MULTIPLIER = {
    "NBA": 1.0,
    "EUROCUP": 0.72,
    "EUROLEAGUE": 0.68,
    "FIBA": 0.65,
}

def detect_league_family(league_text: str):
    if league_text is None:
        return "UNKNOWN"

    t = league_text.lower()
    if "nba" in t:
        return "NBA"
    if "eurocup" in t:
        return "EUROCUP"
    if "euroleague" in t:
        return "EUROLEAGUE"
    if "fiba" in t or "world cup" in t:
        return "FIBA"

    return "UNKNOWN"

def hybrid_baseline_estimator(league_family: str, last5: list, bookmaker_total: float | None):

    default_baseline = LEAGUE_BASELINES.get(league_family, 160.0)

    if bookmaker_total:
        weight_bm = 0.55
        weight_nf = 0.35
        weight_history = 0.10
    else:
        weight_bm = 0.00
        weight_nf = 0.70
        weight_history = 0.30

    nf_baseline = default_baseline

    if last5 and len(last5) >= 3:
        history_baseline = statistics.mean(last5)
    else:
        history_baseline = default_baseline

    if bookmaker_total:
        merged = (
            bookmaker_total * weight_bm
            + nf_baseline * weight_nf
            + history_baseline * weight_history
        )
    else:
        merged = nf_baseline * weight_nf + history_baseline * weight_history

    # Momentum düzeltmesi
    if last5 and len(last5) >= 5:
        dif = last5[-1] - last5[-5]
        merged += (dif * 0.05)

    return merged


# ============================================================
#   N O R M A L İ Z E   B Ö L Ü M L E R
# ============================================================

def normalize_api_data(api_raw):
    if api_raw is None:
        return {}
    return {
        "home": api_raw.get("home"),
        "away": api_raw.get("away"),
        "league": api_raw.get("league"),
        "total": api_raw.get("total"),
    }

def normalize_manual_text(text_raw):
    if not text_raw:
        return {}
    return {"manual_text": text_raw}


def normalize_visual_meta(meta_raw):
    return meta_raw or {}


# ============================================================
#   F A Z - 1 3   A U T O   P I P E L I N E
# ============================================================

def run_faz13_auto_pipeline(api_data, visual_data, manual_data, history_data):

    nd_api = normalize_api_data(api_data)
    nd_visual = normalize_visual_meta(visual_data)
    nd_manual = normalize_manual_text(manual_data)

    league_family = detect_league_family(nd_api.get("league"))

    last5 = history_data.get("last5_totals", []) if history_data else []

    bookmaker_total = nd_visual.get("bookmaker_total")

    hybrid_value = hybrid_baseline_estimator(
        league_family=league_family,
        last5=last5,
        bookmaker_total=bookmaker_total
    )

    if bookmaker_total:
        band_low = hybrid_value - 4.0
        band_high = hybrid_value + 4.0
    else:
        band_low = hybrid_value - 8.0
        band_high = hybrid_value + 8.0

    result = {
        "league_family": league_family,
        "hybrid_baseline": round(hybrid_value, 1),
        "band": (round(band_low, 1), round(band_high, 1)),
        "vector": (
            round(band_low, 1),
            round(hybrid_value, 1),
            round(band_high, 1)
        ),
        "debug": {
            "api": nd_api,
            "visual": nd_visual,
            "manual": nd_manual,
            "last5": last5,
            "bookmaker_total": bookmaker_total,
        }
    }

    return result
