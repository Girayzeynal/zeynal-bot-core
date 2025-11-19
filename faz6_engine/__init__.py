# faz6_engine/__init__.py
# Tek dosyalı FAZ-6 çekirdeği (Preset + Prediction Filter + Stake + Portfolio + 4-Seviye Kuponluk ham veri)

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TypedDict


# ============================================================
#                PRESET / MOD AYARLARI
# ============================================================

@dataclass
class ModePreset:
    code: str
    title: str
    min_confidence: float
    min_edge: float
    max_picks: int
    base_stake: float


_PRESETS: Dict[str, ModePreset] = {
    "test": ModePreset("TEST", "FAZ-6 Test Modu", 0.00, 0.00, 6, 1.0),
    "auto": ModePreset("AUTO", "FAZ-6 Otomatik", 0.55, 0.01, 8, 1.0),
    "risk": ModePreset("RISK", "FAZ-6 Risk", 0.52, 0.005, 10, 1.2),
    "edge": ModePreset("EDGE", "FAZ-6 Edge", 0.60, 0.02, 6, 1.3),
    "real": ModePreset("REAL", "FAZ-6 Gerçekçilik", 0.58, 0.015, 7, 1.0),
    "balance": ModePreset("BAL", "FAZ-6 Denge", 0.56, 0.012, 7, 1.1),
}


def get_preset(mode: str) -> ModePreset:
    key = (mode or "auto").lower().strip()
    return _PRESETS.get(key, _PRESETS["auto"])


# ============================================================
#                        PREDICTION TİPİ
# ============================================================

class Prediction(TypedDict):
    id: str
    league: str
    match: str
    pick: str
    market: str
    confidence: float
    edge: float


EngineResult = Dict[str, Any]


# ============================================================
#           GEÇİCİ — FAZ-5 ENTEGRASYON YOLDA
# ============================================================

def _base_predictions() -> List[Prediction]:
    """
    Stabil demo dataset — FAZ-5 bağlanınca otomatik değişecek.
    """
    return [
        {
            "id": "NBA:LAL@DEN",
            "league": "NBA",
            "match": "LAL@DEN",
            "pick": "DEN -4.5",
            "market": "spread",
            "confidence": 0.61,
            "edge": 0.032,
        },
        {
            "id": "NBA:BOS@MIA",
            "league": "NBA",
            "match": "BOS@MIA",
            "pick": "UNDER 224.5",
            "market": "total",
            "confidence": 0.63,
            "edge": 0.036,
        },
        {
            "id": "EL:FENER@OLY",
            "league": "EuroLeague",
            "match": "FENER@OLY",
            "pick": "OLYMPIACOS -3.5",
            "market": "spread",
            "confidence": 0.64,
            "edge": 0.041,
        },
        {
            "id": "EL:EFES@REAL",
            "league": "EuroLeague",
            "match": "EFES@REAL",
            "pick": "REAL MADRID -5.5",
            "market": "spread",
            "confidence": 0.66,
            "edge": 0.045,
        },
        {
            "id": "NBA:GSW@PHX",
            "league": "NBA",
            "match": "GSW@PHX",
            "pick": "OVER 230.5",
            "market": "total",
            "confidence": 0.59,
            "edge": 0.028,
        },
        {
            "id": "NBA:CHI@NYK",
            "league": "NBA",
            "match": "CHI@NYK",
            "pick": "NYK ML",
            "market": "moneyline",
            "confidence": 0.60,
            "edge": 0.031,
        },
    ]


# ============================================================
#         FİLTRE — RANK — STAKE HESABI
# ============================================================

def filter_and_rank_predictions(predictions: List[Prediction], preset: ModePreset) -> List[Prediction]:
    filtered: List[Prediction] = [
        p
        for p in predictions
        if p.get("confidence", 0.0) >= preset.min_confidence
        and p.get("edge", 0.0) >= preset.min_edge
    ]

    filtered.sort(
        key=lambda p: (p.get("edge", 0.0), p.get("confidence", 0.0)),
        reverse=True,
    )

    selected = filtered[: preset.max_picks]

    for p in selected:
        conf = float(p.get("confidence", 0.0))
        edge = float(p.get("edge", 0.0))
        score = max(edge, 0.0005) * conf
        units = 0.5 + score * 10.0
        stake = preset.base_stake * units
        p["recommended_stake"] = round(stake, 2)

    return selected


# ============================================================
#                   ANA FAZ-6 MOTORU
# ============================================================

def run_faz6_engine(mode: str = "auto", context: Optional[Dict[str, Any]] = None) -> EngineResult:
    if context is None:
        context = {}

    mode_norm = (mode or "auto").lower().strip()
    context["requested_mode"] = mode_norm

    preset = get_preset(mode_norm)

    try:
        raw_preds = _base_predictions()
        final = filter_and_rank_predictions(raw_preds, preset)

        return {
            "status": "ok",
            "mode": mode_norm,
            "result": {
                "predictions": final,
                "portfolio": final,
                "meta": {
                    "preset": preset.__dict__,
                    "total_input": len(raw_preds),
                    "total_output": len(final),
                },
            },
            "context": context,
        }

    except Exception as e:
        return {
            "status": "error",
            "mode": mode_norm,
            "detail": f"FAZ-6 engine exception: {repr(e)}",
            "result": {"predictions": [], "portfolio": [], "meta": {}},
            "context": context,
        }


# ============================================================
#        4-SEVİYE KUPON MOTORU (SAFE / BALANCED / AGG / ULTRA)
# ============================================================

def build_coupon_message(engine_result: Dict[str, Any], max_coupons: int = 4) -> str:
    status = engine_result.get("status", "ok")
    if status != "ok":
        return f"❌ *FAZ-6 KUPON HATASI*\n{engine_result.get('detail','Bilinmeyen hata')}"

    preds = (
        engine_result.get("result", {})
        .get("portfolio")
        or engine_result.get("result", {})
        .get("predictions")
        or []
    )

    if not preds:
        return "⚠ Kupon oluşturmak için yeterli maç bulunamadı."

    safe = preds[:2]
    balanced = preds[2:4]
    aggressive = preds[4:5]
    ultra = preds[5:6]

    buckets = [
        ("SAFE", safe),
        ("BALANCED", balanced),
        ("AGGRESSIVE", aggressive),
        ("ULTRA", ultra),
    ]

    out = ["🔥 *FAZ-6 KUPONLARI (4-Seviyeli AI Dağılım)*\n"]

    for idx, (title, group) in enumerate(buckets, start=1):
        if not group:
            continue
        out.append(f"🔥 *Kupon {idx} — {title}*")
        total = 0.0

        for p in group:
            stake = float(p.get("recommended_stake", 0))
            total += stake
            out.append(
                f"- {p['id']} | {p['pick']} ({p['market']})\n"
                f"  Güven: {p['confidence']} | Edge: {p['edge']} | Stake: {stake}"
            )

        out.append(f"💰 Toplam Stake: {round(total, 2)}\n— — —")

    text = "\n".join(out)
    if len(text) > 3900:
        text = text[:3900] + "\n… (çıktı kısaltıldı)"

    return text


__all__ = ["run_faz6_engine", "build_coupon_message"]
