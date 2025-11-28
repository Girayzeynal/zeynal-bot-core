import time
import math
from typing import Dict, Any, Optional, Tuple, List

from .models import (
    MatchMeta,
    FazMemory,
    Faz13Score,
    Faz9TrendInput,
    Faz9TrendOutput,
    GodLayerOutput,
)


# ================================================================
# 🧰 Yardımcı Fonksiyonlar
# ================================================================
def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(str(val).replace(",", "."))
    except Exception:
        return default


def _clip(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


# ================================================================
# 🧠 FAZ-7.9 MEMORY ENGINE
# ================================================================
def faz7_init_memory() -> FazMemory:
    """Boş bir FAZ-7 hafıza objesi döner."""
    return FazMemory(days=[], safe=0.0, bal=0.0, agg=0.0)


def faz7_update_memory(
    memory: FazMemory,
    conf: float,
    edge: float,
    ts: Optional[int] = None,
    window_days: int = 7,
) -> FazMemory:
    """
    FAZ-7.9 hafıza motoru:
    - Son N günün (varsayılan 7) conf/edge değerlerini saklar
    - safe / bal / agg ortalamalarını hesaplar
    """
    if ts is None:
        ts = int(time.time())

    # Yeni gün kaydı ekle
    memory.days.append({"ts": ts, "conf": float(conf), "edge": float(edge)})

    # Eski kayıtları temizle (rolling window)
    cutoff = ts - window_days * 24 * 3600
    memory.days = [d for d in memory.days if d.get("ts", 0) >= cutoff]

    if not memory.days:
        memory.safe = 0.0
        memory.bal = 0.0
        memory.agg = 0.0
        return memory

    # Ortalama conf / edge
    avg_conf = sum(d["conf"] for d in memory.days) / len(memory.days)
    avg_edge = sum(d["edge"] for d in memory.days) / len(memory.days)

    # Safe / Bal / Agg profil ağırlıkları
    # (Eski FAZ-12 mantığına yakın ama sadeleştirilmiş)
    memory.safe = _clip(avg_conf - abs(avg_edge) * 2.0, 0.0, 1.0)
    memory.agg = _clip(avg_conf + avg_edge * 3.0, 0.0, 1.0)
    memory.bal = _clip((memory.safe + memory.agg) / 2.0, 0.0, 1.0)

    return memory


# ================================================================
# 📉 FAZ-9.x TREND ENGINE (TCI / Noise / BehaviorIndex)
# ================================================================
def faz9_compute_trend(memory: FazMemory) -> Faz9TrendOutput:
    """
    FAZ-9.x trend & noise hesapları.
    Çok ağır istatistik yok, hafif ama anlamlı bir metrik.
    """
    if not memory.days:
        return Faz9TrendOutput(tci=0.0, noise=0.0, behavior_index=0.0)

    conf_list = [float(d["conf"]) for d in memory.days]
    edge_list = [float(d["edge"]) for d in memory.days]

    # Volatilite ~ edge oynaklığı
    mean_edge = sum(edge_list) / len(edge_list)
    var_edge = sum((e - mean_edge) ** 2 for e in edge_list) / max(1, len(edge_list) - 1)
    vol = math.sqrt(var_edge)

    # TCI (Trend Confidence Index):
    #   yüksek conf, pozitif edge, düşük vol -> yüksek skor
    avg_conf = sum(conf_list) / len(conf_list)
    avg_edge = mean_edge

    tci_raw = avg_conf + avg_edge - vol
    tci = _clip(tci_raw, -1.0, 1.0)

    # Noise Ratio: vol / (|edge| + epsilon)
    denom = abs(avg_edge) + 1e-4
    noise = _clip(vol / denom, 0.0, 5.0)

    # Behavior Index: safe/bal/agg dağılımından çıkan bir momentum
    behavior_index = _clip(
        (memory.agg - memory.safe) * 0.5 + avg_conf * 0.5,
        -1.0,
        1.0,
    )

    return Faz9TrendOutput(tci=tci, noise=noise, behavior_index=behavior_index)


# ================================================================
# 🎯 FAZ-13 PREDICTION & BUCKET ENGINE
# ================================================================
def _compute_bucket_and_risk(conf: float, edge: float) -> Tuple[str, str]:
    """
    Basit ama pratik bucket/risk haritası:
      - HIGH / HIGH
      - MID / MEDIUM
      - LOW / LOW
    """
    c = conf
    e = edge

    if c >= 0.72 and e >= 0.02:
        return "HIGH", "HIGH"
    if c >= 0.6 and e >= 0.0:
        return "MID", "MEDIUM"
    return "LOW", "LOW"


def faz13_compute_score(
    meta: MatchMeta,
    memory: FazMemory,
    trend: Faz9TrendOutput,
) -> Faz13Score:
    """
    FAZ-13 ana skor motoru.
    Input:
      - normalize edilmiş meta (MatchMeta)
      - FAZ-7 memory
      - FAZ-9 trend
    Output:
      - Conf / Edge / Bucket / Risk / ImpliedP / Score
    """
    # Odds -> implied prob
    odds = _safe_float(meta.odds, default=0.0)
    if odds > 1.0:
        implied_p = _clip(1.0 / odds, 0.0, 1.0)
    else:
        implied_p = 0.0

    # Base conf: memory + trend birleşimi
    base_conf = 0.5
    base_conf += (memory.bal - 0.5) * 0.4
    base_conf += trend.tci * 0.2
    base_conf = _clip(base_conf, 0.0, 1.0)

    # Edge: model conf vs implied prob
    edge = base_conf - implied_p

    bucket, risk = _compute_bucket_and_risk(base_conf, edge)

    # Final score: normalized, 0-100 bandında
    score = _clip((base_conf * 0.7 + (edge + 0.1) * 0.3) * 100.0, 0.0, 100.0)

    return Faz13Score(
        conf=round(base_conf, 3),
        edge=round(edge, 3),
        bucket=bucket,
        risk=risk,
        implied_p=round(implied_p, 3),
        score=round(score, 1),
    )


# ================================================================
# 🔮 GOD-LAYER PIPELINE
# ================================================================
def god_layer_run(
    source_type: str,
    meta: MatchMeta,
    memory: FazMemory,
    faz11_feedback: Optional[Dict[str, Any]] = None,
    faz12_decision: Optional[Dict[str, Any]] = None,
) -> GodLayerOutput:
    """
    Tek fonksiyon → GOD-LAYER:
      1) FAZ-9 trend hesapla
      2) FAZ-13 skor üret
      3) FAZ-11 / FAZ-12 verisini fuse et
      4) Tek struct döndür
    """
    trend = faz9_compute_trend(memory)
    score_obj = faz13_compute_score(meta, memory, trend)

    # Çıktıları dict'e çevir
    score = score_obj.to_dict()
    meta_dict = meta.to_dict()

    # Trend bilgilerini de score içine göm (debug & gelişmiş analiz için)
    score["tci"] = round(trend.tci, 3)
    score["noise"] = round(trend.noise, 3)
    score["behavior_index"] = round(trend.behavior_index, 3)

    return GodLayerOutput(
        source_type=source_type,
        meta=meta_dict,
        score=score,
        faz11_feedback=faz11_feedback,
        faz12_decision=faz12_decision,
    )


# ================================================================
# 🧪 MINI SIMÜLASYON YARDIMCILARI
# ================================================================
def simulate_outcome_once(score: Faz13Score) -> bool:
    """
    Tek deneme simülasyonu:
    - Score / conf / edge'e göre basit bir başarı olasılığı kurar
    - True: isabet
    - False: kaçan
    """
    # Baz başarı olasılığı: conf
    p = _clip(score.conf, 0.0, 1.0)

    # Edge pozitifse biraz boost, negatifse kırp
    p += score.edge * 0.5
    p = _clip(p, 0.0, 1.0)

    # Çok kaba ama hızlı bir RNG yerine: deterministic pseudo (seed yoksa)
    # Kullanıcı gerçek simülasyon isterse external RNG bağlayabilir.
    t = time.time()
    frac = t - int(t)
    return frac < p


def simulate_n(
    score: Faz13Score,
    n: int = 100_000,
) -> Dict[str, Any]:
    """
    FAZ-13 mini simülasyon:
    n deneme üzerinden kaç isabet / kaç kaçan gibi özet verir.
    Gerçek random yerine zaman tabanlı kaba RNG kullanır (deterministic
    olması şart değil, sadece fikir vermek için).
    """
    n = max(1, n)
    hits = 0
    for _ in range(n):
        if simulate_outcome_once(score):
            hits += 1

    hit_rate = hits / n
    return {
        "trials": n,
        "hits": hits,
        "hit_rate": round(hit_rate, 4),
    }


# ================================================================
# 🚀 YÜKSEK SEVİYE KOLAY KULLANIM FONKSİYONU
# ================================================================
def run_full_pipeline(
    source_type: str,
    meta_raw: Dict[str, Any],
    memory_state: Optional[Dict[str, Any]] = None,
    faz11_feedback: Optional[Dict[str, Any]] = None,
    faz12_decision: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Dış dünyaya açılan ana fonksiyon.

    Kullanım:
        state = None
        out = run_full_pipeline(
            source_type="manual",
            meta_raw={
                "source": "manual",
                "raw": "/mac BOS ORL 220.5 U 1.46",
                "league": "NBA",
                "home": "BOS",
                "away": "ORL",
                "market": "FT TOTAL",
                "line": 220.5,
                "direction": "U",
                "odds": 1.46,
            },
            memory_state=state,
        )
        state = out["memory"]

    Dönen:
        {
          "meta": {...},
          "score": {...},
          "memory": {...},
          "god_layer": {...},
        }
    """
    # Memory load/init
    if memory_state is None:
        memory = faz7_init_memory()
    else:
        memory = FazMemory(
            days=memory_state.get("days", []),
            safe=_safe_float(memory_state.get("safe", 0.0)),
            bal=_safe_float(memory_state.get("bal", 0.0)),
            agg=_safe_float(memory_state.get("agg", 0.0)),
        )

    # Meta objesi oluştur
    meta = MatchMeta(
        source=meta_raw.get("source", source_type),
        raw=meta_raw.get("raw", ""),
        league=meta_raw.get("league", "NBA"),
        home=meta_raw.get("home", "UNKNOWN"),
        away=meta_raw.get("away", "UNKNOWN"),
        market=meta_raw.get("market", "FT TOTAL"),
        line=_safe_float(meta_raw.get("line"), None),
        direction=meta_raw.get("direction"),
        odds=_safe_float(meta_raw.get("odds"), None),
    )

    # FAZ-7 memory update (şimdilik tek kayıt: conf ipucu olarak line/odds kullanmıyoruz;
    # dış model conf/edge verirsen burada kullanabilirsin)
    # Şimdilik conf için 0.6, edge için 0.0 gibi nötr değerler atıyoruz
    memory = faz7_update_memory(memory, conf=0.6, edge=0.0)

    # GOD-LAYER çalıştır
    god = god_layer_run(
        source_type=source_type,
        meta=meta,
        memory=memory,
        faz11_feedback=faz11_feedback,
        faz12_decision=faz12_decision,
    )

    return {
        "meta": meta.to_dict(),
        "score": god.score,
        "memory": memory.to_dict(),
        "god_layer": god.to_dict(),
    }
