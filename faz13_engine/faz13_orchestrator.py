from __future__ import annotations
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional
from .league_autodetect import guess_league
from .faz13_news_scraper import MatchMeta, get_match_news, encode_news_features

import os
import json
import time

log = logging.getLogger(__name__)

# ================================================================
# GLOBAL LIG AİLESİ KONFİGÜRASYONU
# ================================================================
FAMILY_CONFIG: Dict[str, Dict[str, Any]] = {
    # Kuzey Amerika
    "NBA": {"base_total": 230.0, "q_dist": [0.24, 0.26, 0.25, 0.25], "pace_volatility": 0.12, "defense_volatility": 0.10, "home_adv": 3.0},
    "WNBA": {"base_total": 165.0, "q_dist": [0.24, 0.26, 0.25, 0.25], "pace_volatility": 0.11, "defense_volatility": 0.10, "home_adv": 2.5},
    "GLEAGUE": {"base_total": 225.0, "q_dist": [0.25, 0.25, 0.25, 0.25], "pace_volatility": 0.13, "defense_volatility": 0.11, "home_adv": 2.5},
    # Avrupa üst seviye
    "EUROLEAGUE": {"base_total": 165.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.10, "defense_volatility": 0.11, "home_adv": 3.5},
    "EUROCUP": {"base_total": 162.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.10, "defense_volatility": 0.11, "home_adv": 3.0},
    "BCL": {"base_total": 159.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.11, "defense_volatility": 0.11, "home_adv": 3.0},
    # Milli takım / FIBA
    "FIBA_NATIONAL": {"base_total": 155.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.09, "defense_volatility": 0.11, "home_adv": 2.5},
    # Yerel lig aileleri (örnekler)
    "TURKISH_BSL": {"base_total": 160.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.11, "defense_volatility": 0.11, "home_adv": 3.5},
    "ACB_SPAIN": {"base_total": 162.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.11, "defense_volatility": 0.11, "home_adv": 3.0},
    "GERMANY_BBL": {"base_total": 164.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.11, "defense_volatility": 0.11, "home_adv": 3.0},
    "FRANCE_PROA": {"base_total": 161.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.11, "defense_volatility": 0.11, "home_adv": 3.0},
    "ITALY_SERIEA": {"base_total": 160.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.11, "defense_volatility": 0.11, "home_adv": 3.0},
    "GREECE_ESAKE": {"base_total": 158.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.10, "defense_volatility": 0.11, "home_adv": 3.5},
    "ABA_ADRIATIC": {"base_total": 162.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.11, "defense_volatility": 0.11, "home_adv": 3.0},
    # Diğer global lig aileleri
    "AUSTRALIA_NBL": {"base_total": 171.0, "q_dist": [0.24, 0.26, 0.25, 0.25], "pace_volatility": 0.11, "defense_volatility": 0.10, "home_adv": 3.0},
    "JAPAN_BLEAGUE": {"base_total": 178.0, "q_dist": [0.24, 0.26, 0.25, 0.25], "pace_volatility": 0.12, "defense_volatility": 0.10, "home_adv": 2.5},
    "KOREA_KBL": {"base_total": 176.0, "q_dist": [0.24, 0.26, 0.25, 0.25], "pace_volatility": 0.12, "defense_volatility": 0.10, "home_adv": 2.5},
    "CHINA_CBA": {"base_total": 184.0, "q_dist": [0.24, 0.26, 0.25, 0.25], "pace_volatility": 0.13, "defense_volatility": 0.10, "home_adv": 3.0},
    "PHILIPPINES_PBA": {"base_total": 182.0, "q_dist": [0.24, 0.26, 0.25, 0.25], "pace_volatility": 0.12, "defense_volatility": 0.10, "home_adv": 3.0},
    # Genel default family
    "GENERIC_HIGH": {"base_total": 175.0, "q_dist": [0.24, 0.26, 0.25, 0.25], "pace_volatility": 0.11, "defense_volatility": 0.10, "home_adv": 3.0},
    "GENERIC_MID": {"base_total": 165.0, "q_dist": [0.23, 0.27, 0.25, 0.25], "pace_volatility": 0.10, "defense_volatility": 0.11, "home_adv": 3.0},
    "GENERIC_LOW": {"base_total": 155.0, "q_dist": [0.22, 0.28, 0.25, 0.25], "pace_volatility": 0.09, "defense_volatility": 0.12, "home_adv": 3.0},
}

# ================================================================
# 🔥 HYBRID BASELINE ENGINE (yeni eklenen bölüm)
# ================================================================
FAZ13_DATA_DIR = os.getenv("FAZ13_DATA_DIR", "/data/faz13")
FAZ13_BASELINE_STATE_PATH = os.path.join(FAZ13_DATA_DIR, "faz13_baseline_state.json")

def _faz13_ensure_dir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass

def _load_baseline_state() -> Dict[str, Dict[str, float]]:
    try:
        if not os.path.exists(FAZ13_BASELINE_STATE_PATH):
            return {}
        with open(FAZ13_BASELINE_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}

def _save_baseline_state(state: Dict[str, Dict[str, float]]) -> None:
    try:
        _faz13_ensure_dir(os.path.dirname(FAZ13_BASELINE_STATE_PATH))
        tmp_path = FAZ13_BASELINE_STATE_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, FAZ13_BASELINE_STATE_PATH)
    except Exception:
        pass

def _update_dynamic_baseline_for_family(
    league_family: str,
    family_base: float,
    news_total_hint: float | None = None,
) -> Tuple[float, str]:
    try:
        family_base = float(family_base)
    except Exception:
        family_base = float(family_base or 0.0)

    target = family_base
    if news_total_hint is not None and news_total_hint > 0:
        target = (family_base * 0.6) + (news_total_hint * 0.4)

    state = _load_baseline_state()
    fam_state = state.get(league_family) or {}
    current = fam_state.get("baseline")
    if current is None:
        current = family_base
    try:
        current = float(current)
    except Exception:
        current = family_base

    delta = target - current
    max_step = 0.5
    if abs(delta) > max_step:
        step = max_step if delta > 0 else -max_step
    else:
        step = delta
    new_baseline = float(current + step)

    state[league_family] = {
        "baseline": new_baseline,
        "ts": time.time(),
        "family_base": float(family_base),
        "target": float(target),
    }
    _save_baseline_state(state)

    debug = (
        f"HYBRID baseline[{league_family}] "
        f"family_base={family_base:.1f} target={target:.1f} "
        f"prev={current:.1f} new={new_baseline:.1f}"
    )
    return new_baseline, debug

# ================================================================
# (… geriye kalan eski yardımcı fonksiyonlar: _league_family, _safe_float, _detect_match_from_text, _baseline_total_for_league, _national_match_flag, _compute_team_total_shares, normalize_manual_text, normalize_visual_meta, normalize_api_data, _faz23_recommendation)
# — Bunlar aynen eski hâllerinde kalacak.
# ================================================================
