# faz23_engine/faz23_max.py

import time
import math
import hashlib
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

import numpy as np
import json
from pathlib import Path


# ================================================================
#  CONFIG
# ================================================================

@dataclass
class Faz23MaxConfig:
    base_iter: int = 500           # başlangıç iter
    max_iter: int = 2400           # adaptif üst sınır (Fly free dostu)
    low_uncert_spread: float = 12.0
    high_uncert_spread: float = 26.0
    cache_limit: int = 60          # RAM'de tutulan maç sayısı
    min_total: float = 120.0       # toplam skor alt sınır
    max_total: float = 260.0       # toplam skor üst sınır
    history_path: str = "/data/faz23_history.jsonl"


FAZ23_MAX_CACHE: Dict[str, Dict[str, Any]] = {}


def _trim_cache(limit: int) -> None:
    """RAM patlamasın diye cache budama."""
    global FAZ23_MAX_CACHE
    if len(FAZ23_MAX_CACHE) <= limit:
        return
    items = sorted(
        FAZ23_MAX_CACHE.items(),
        key=lambda kv: kv[1].get("ts", 0)
    )
    for k, _ in items[:-limit]:
        FAZ23_MAX_CACHE.pop(k, None)


# ================================================================
#  MATCH CODE
# ================================================================

def build_match_code(meta: Dict[str, Any]) -> str:
    parts = [
        meta.get("league", "NA"),
        meta.get("season", "NA"),
        meta.get("home", "HOME"),
        meta.get("away", "AWAY"),
        meta.get("type", "club"),
        meta.get("stage", "league"),
        str(meta.get("start_ts", int(time.time()))),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ================================================================
#  FUSION VEKTÖRÜ (12 PARAMETRE)
# ================================================================

def build_fusion_vector(raw: Dict[str, Any]) -> Dict[str, float]:
    """
    FAZ-13 / FAZ-17 meta'sından 12 boyutlu fusion vektörü.
    Eksik gelenler 1.0 / default'a düşer.
    """
    base_total = float(raw.get("base_total", 165.0))
    tempo_factor = float(raw.get("tempo_factor", 1.0))
    defense_factor = float(raw.get("defense_factor", 1.0))
    pace_volatility = float(raw.get("pace_volatility", 1.0))
    defense_volatility = float(raw.get("defense_volatility", 1.0))
    home_adv = float(raw.get("home_adv", 1.0))
    h2h_factor = float(raw.get("h2h_factor", 1.0))
    hot_risk = float(raw.get("hot_shooting_risk", 1.0))
    clutch_factor = float(raw.get("clutch_factor", 1.0))
    national_bonus = float(raw.get("national_bonus", 1.0))
    fatigue = float(raw.get("schedule_fatigue", 1.0))
    style_pace = float(raw.get("style_pace", 1.0))

    out = {
        "base_total": base_total,
        "tempo_factor": tempo_factor,
        "defense_factor": defense_factor,
        "pace_volatility": pace_volatility,
        "defense_volatility": defense_volatility,
        "home_adv": home_adv,
        "h2h_factor": h2h_factor,
        "hot_shooting_risk": hot_risk,
        "clutch_factor": clutch_factor,
        "national_bonus": national_bonus,
        "schedule_fatigue": fatigue,
        "style_pace": style_pace,
    }

    # saçma değer gelirse normalize et
    for k, v in out.items():
        if not np.isfinite(v):
            out[k] = 1.0

    return out


# ================================================================
#  3 ÇEKİRDEKLİ MIXTURE PARAMETRELERİ
# ================================================================

def _build_mixture_params(
    fusion: Dict[str, float],
    national: bool
) -> Dict[str, Any]:
    base_total = fusion["base_total"]
    tempo = fusion["tempo_factor"] * fusion["style_pace"]
    defense = fusion["defense_factor"]
    pace_vol = fusion["pace_volatility"]
    def_vol = fusion["defense_volatility"]
    home_adv = fusion["home_adv"]
    h2h_factor = fusion["h2h_factor"]
    hot_risk = fusion["hot_shooting_risk"]
    clutch = fusion["clutch_factor"]
    fatigue = fusion["schedule_fatigue"]
    national_bonus = fusion["national_bonus"] if national else 1.0

    # temel skor
    mu_base = base_total * tempo * defense * national_bonus
    mu_base *= home_adv * h2h_factor

    # 3 farklı çekirdek:
    # 1) tempo / sıcak şut riski
    mu1 = mu_base * (1.0 + 0.015 * hot_risk - 0.01 * fatigue)
    # 2) savunma / clutch
    mu2 = mu_base * (0.98 + 0.01 * clutch)
    # 3) tempo vs defense dengesizlik
    mu3 = mu_base * (1.0 + 0.01 * (pace_vol - def_vol))

    sigma1 = max(8.0, mu1 * 0.06 * pace_vol)
    sigma2 = max(6.0, mu2 * 0.055 * def_vol)
    sigma3 = max(9.0, mu3 * 0.065 * (pace_vol + def_vol) / 2.0)

    w1 = 0.4 + 0.2 * (tempo - 1.0)
    w2 = 0.35 + 0.1 * (defense - 1.0)
    w3 = 1.0 - (w1 + w2)

    w1 = float(np.clip(w1, 0.2, 0.6))
    w2 = float(np.clip(w2, 0.2, 0.5))
    w3 = float(np.clip(w3, 0.1, 0.4))

    s = w1 + w2 + w3
    w1 /= s
    w2 /= s
    w3 /= s

    return {
        "mu": (mu1, mu2, mu3),
        "sigma": (sigma1, sigma2, sigma3),
        "w": (w1, w2, w3),
    }


def _sample_totals(
    n: int,
    mix: Dict[str, Any],
    cfg: Faz23MaxConfig
) -> np.ndarray:
    """3 çekirdekli mixture'dan skor çekimi."""
    w1, w2, w3 = mix["w"]
    u = np.random.rand(n)
    k1 = u < w1
    k2 = (u >= w1) & (u < w1 + w2)
    k3 = ~(k1 | k2)

    mu1, mu2, mu3 = mix["mu"]
    s1, s2, s3 = mix["sigma"]

    totals = np.empty(n)

    c1 = int(k1.sum())
    c2 = int(k2.sum())
    c3 = int(k3.sum())

    if c1 > 0:
        totals[k1] = np.random.normal(mu1, s1, size=c1)
    if c2 > 0:
        totals[k2] = np.random.normal(mu2, s2, size=c2)
    if c3 > 0:
        totals[k3] = np.random.normal(mu3, s3, size=c3)

    return np.clip(totals, cfg.min_total, cfg.max_total)


def _adaptive_draws(
    fusion: Dict[str, float],
    national: bool,
    cfg: Faz23MaxConfig
) -> (np.ndarray, Dict[str, Any]):
    """Belirsizliğe göre iter sayısını adaptif ayarlar."""
    mix = _build_mixture_params(fusion, national)
    draws = _sample_totals(cfg.base_iter, mix, cfg)
    q30, q70 = np.quantile(draws, [0.30, 0.70])
    spread = float(q70 - q30)

    if spread > cfg.high_uncert_spread:
        iters = cfg.base_iter
    elif spread < cfg.low_uncert_spread:
        ratio = cfg.low_uncert_spread / max(spread, 1.0)
        iters = int(min(cfg.max_iter, cfg.base_iter * ratio * 1.6))
    else:
        iters = int(cfg.base_iter * 1.7)

    if iters > cfg.base_iter:
        draws = _sample_totals(iters, mix, cfg)

    debug = {
        "iters": iters,
        "spread_initial": spread,
        "mix": mix,
    }
    return draws, debug


# ================================================================
#  DAĞILIM ANALİZİ
# ================================================================

def _analyze_distribution(
    draws: np.ndarray
) -> Dict[str, Any]:
    mean_total = float(np.mean(draws))
    q10, q30, q70, q90 = np.quantile(draws, [0.10, 0.30, 0.70, 0.90])
    band_narrow = [int(round(q30)), int(round(q70))]
    band_wide = [int(round(q10)), int(round(q90))]

    hist, _ = np.histogram(draws, bins=14, density=True)
    hist = hist + 1e-9
    entropy = -float(np.sum(hist * np.log(hist)))

    spread_narrow = float(band_narrow[1] - band_narrow[0])

    if spread_narrow <= 10:
        risk_bucket = "low"
    elif spread_narrow <= 18:
        risk_bucket = "medium"
    else:
        risk_bucket = "high"

    return {
        "mean_total": mean_total,
        "band_narrow": band_narrow,
        "band_wide": band_wide,
        "entropy": entropy,
        "spread_narrow": spread_narrow,
        "risk_bucket": risk_bucket,
    }


# ================================================================
#  BAREM GRID ANALİZİ
# ================================================================

def _evaluate_barems(
    draws: np.ndarray,
    dist_info: Dict[str, Any],
    barem_grid: List[float]
) -> Dict[str, Any]:
    band_narrow = dist_info["band_narrow"]
    mean_total = dist_info["mean_total"]
    entropy = dist_info["entropy"]

    grid_results = []
    best_pick: Optional[Dict[str, Any]] = None
    best_score = -1.0

    for barem in barem_grid:
        barem = float(barem)
        p_over = float(np.mean(draws > barem))
        p_under = 1.0 - p_over
        direction = "over" if p_over > p_under else "under"
        main_prob = max(p_over, p_under)

        diff = mean_total - barem
        angle = math.degrees(
            math.atan(abs(diff) / max(1.0, band_narrow[1] - band_narrow[0]))
        )
        angle_score = min(angle / 50.0, 1.0)

        chaos = min(entropy / 3.2, 1.0)

        spread_score = 1.0 - min(
            (band_narrow[1] - band_narrow[0]) / 32.0, 1.0
        )
        chaos_score = 1.0 - 0.6 * chaos

        confidence = 100.0 * max(
            0.25,
            min(
                0.96,
                0.38 * main_prob
                + 0.32 * spread_score
                + 0.30 * angle_score * chaos_score,
            ),
        )

        score_for_pick = confidence

        item = {
            "barem": barem,
            "direction": direction,
            "p_over": p_over,
            "p_under": p_under,
            "main_prob": main_prob,
            "angle_deg": angle,
            "confidence": confidence,
        }
        grid_results.append(item)

        if score_for_pick > best_score:
            best_score = score_for_pick
            best_pick = item

    return {
        "grid": grid_results,
        "best_pick": best_pick,
    }


# ================================================================
#  HISTORY YAZIMI
# ================================================================

def _append_history(path: str, record: Dict[str, Any]) -> None:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # history patlarsa bile ana tahmin akmasın
        pass


# ================================================================
#  ANA API
# ================================================================

def faz23_max_predict(
    match_meta: Dict[str, Any],
    fusion_input: Dict[str, Any],
    barem_grid: List[float],
    cfg: Faz23MaxConfig | None = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    FAZ-23 MAX ana fonksiyon:
    - fusion_input → 12D fusion vector
    - 3 kernel mixture + adaptif iter
    - barem grid analizi
    - history kaydı
    """
    global FAZ23_MAX_CACHE

    if cfg is None:
        cfg = Faz23MaxConfig()

    match_code = build_match_code(match_meta)
    cache_key = f"{match_code}:{','.join([str(b) for b in barem_grid])}"

    if use_cache and cache_key in FAZ23_MAX_CACHE:
        return FAZ23_MAX_CACHE[cache_key]

    fusion = build_fusion_vector(fusion_input)
    national = match_meta.get("type", "club") == "national"

    draws, debug = _adaptive_draws(fusion, national, cfg)
    dist_info = _analyze_distribution(draws)
    barem_info = _evaluate_barems(draws, dist_info, barem_grid)

    result = {
        "match_code": match_code,
        "match_meta": match_meta,
        "fusion": fusion,
        "dist": dist_info,
        "barems": barem_info,
        "debug": debug,
        "ts": int(time.time()),
    }

    FAZ23_MAX_CACHE[cache_key] = result
    _trim_cache(cfg.cache_limit)

    # history satırı
    history_record = {
        "ts": result["ts"],
        "match_code": match_code,
        "league": match_meta.get("league"),
        "home": match_meta.get("home"),
        "away": match_meta.get("away"),
        "type": match_meta.get("type", "club"),
        "dist": dist_info,
        "best_pick": barem_info["best_pick"],
        "barem_grid": barem_grid,
    }
    _append_history(cfg.history_path, history_record)

    return result


# ================================================================
#  YORUM METNİ
# ================================================================

def faz23_max_comment(result: Dict[str, Any]) -> str:
    meta = result.get("match_meta", {})
    dist = result.get("dist", {})
    barems = result.get("barems", {})
    best = barems.get("best_pick")

    band_n = dist.get("band_narrow", [0, 0])
    band_w = dist.get("band_wide", [0, 0])
    risk = dist.get("risk_bucket", "unknown")

    league = meta.get("league", "Lig")
    home = meta.get("home", "HOME")
    away = meta.get("away", "AWAY")

    if not best:
        return (
            f"FAZ-23 MAX | {home} - {away} ({league})\n"
            "Bu maç için anlamlı bir barem kararı çıkmadı."
        )

    yon = "ÜST" if best["direction"] == "over" else "ALT"
    bar = best["barem"]
    conf = int(round(best["confidence"]))
    prob = int(round(best["main_prob"] * 100))
    angle = best["angle_deg"]

    risk_text = {
        "low": "düşük riskli, dağılım sıkışmış.",
        "medium": "orta riskli, skor bandı kontrollü ama esneyebilir.",
        "high": "yüksek riskli, skor dağılımı geniş ve kaotik.",
    }.get(risk, "risk profili belirsiz.")

    txt = (
        f"FAZ-23 MAX | {home} - {away} ({league})\n"
        f"Dar band: {band_n[0]}–{band_n[1]}, geniş band: {band_w[0]}–{band_w[1]}.\n"
        f"Ana aday barem: {bar:.1f} → yön: {yon} "
        f"(model olasılığı ≈ %{prob}, güven ≈ %{conf}).\n"
        f"Barem açısı ≈ {angle:.1f}°. Risk yorumu: {risk_text}"
    )
    return txt
