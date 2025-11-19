# faz6_engine/__init__.py
# Tek dosyalı FAZ-6 çekirdeği: preset + selector + engine + coupon hepsi burada.

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
    "test": ModePreset(
        code="TEST",
        title="FAZ-6 Test Modu",
        min_confidence=0.00,
        min_edge=0.00,
        max_picks=6,
        base_stake=1.0,
    ),
    "auto": ModePreset(
        code="AUTO",
        title="FAZ-6 Otomatik",
        min_confidence=0.55,
        min_edge=0.01,
        max_picks=8,
        base_stake=1.0,
    ),
    "risk": ModePreset(
        code="RISK",
        title="FAZ-6 Risk Modu",
        min_confidence=0.52,
        min_edge=0.005,
        max_picks=10,
        base_stake=1.2,
    ),
    "edge": ModePreset(
        code="EDGE",
        title="FAZ-6 Edge Odaklı",
        min_confidence=0.60,
        min_edge=0.02,
        max_picks=6,
        base_stake=1.3,
    ),
    "real": ModePreset(
        code="REAL",
        title="FAZ-6 Gerçekçilik",
        min_confidence=0.58,
        min_edge=0.015,
        max_picks=7,
        base_stake=1.0,
    ),
    "balance": ModePreset(
        code="BAL",
        title="FAZ-6 Denge",
        min_confidence=0.56,
        min_edge=0.012,
        max_picks=7,
        base_stake=1.1,
    ),
}


def get_preset(mode: str) -> ModePreset:
    key = (mode or "auto").lower().strip()
    return _PRESETS.get(key, _PRESETS["auto"])


# ============================================================
#                    TAHMİN TİPİ
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
#          ÖRNEK / TEMPORARY TAHMİN ÜRETİCİ
# ============================================================

def _base_predictions() -> List[Prediction]:
    """
    Şimdilik FAZ-5 entegrasyonu yok.
    Stabil olsun diye sabit birkaç maç dönüyoruz.
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
#              SEÇİM / SIRALAMA / STAKE HESABI
# ============================================================

def filter_and_rank_predictions(
    predictions: List[Prediction],
    preset: ModePreset,
) -> List[Prediction]:
    """
    - confidence & edge ile filtre
    - edge + confidence’e göre sırala
    - max_picks kadar seçim
    - recommended_stake hesapla
    """

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
#                    ANA FAZ-6 MOTORU
# ============================================================

def run_faz6_engine(
    mode: str = "auto",
    context: Optional[Dict[str, Any]] = None,
) -> EngineResult:
    """
    main.py + format_faz6_message ile uyumlu çekirdek.
    """
    if context is None:
        context = {}

    mode_norm = (mode or "auto").lower().strip()
    context["requested_mode"] = mode_norm

    preset = get_preset(mode_norm)

    try:
        raw_preds = _base_predictions()
        final_preds = filter_and_rank_predictions(raw_preds, preset)

        result_block: Dict[str, Any] = {
            "predictions": final_preds,
            "portfolio": final_preds,
            "meta": {
                "preset": {
                    "code": preset.code,
                    "title": preset.title,
                    "min_confidence": preset.min_confidence,
                    "min_edge": preset.min_edge,
                    "max_picks": preset.max_picks,
                    "base_stake": preset.base_stake,
                },
                "total_input": len(raw_preds),
                "total_output": len(final_preds),
            },
        }

        return {
            "status": "ok",
            "mode": mode_norm,
            "result": result_block,
            "context": context,
        }

    except Exception as e:
        return {
            "status": "error",
            "mode": mode_norm,
            "detail": f"FAZ-6 engine exception: {repr(e)}",
            "result": {
                "predictions": [],
                "portfolio": [],
                "meta": {},
            },
            "context": context,
        }


# ============================================================
#                    KUPON MESAJ ÜRETİCİ
# ============================================================

def build_coupon_message(engine_result: Dict[str, Any],
                         max_coupons: int = 3) -> str:
    """
    FAZ-6 motor çıktısından 3 kuponluk Telegram metni üretir.
    """
    status = engine_result.get("status", "ok")
    if status != "ok":
        detail = engine_result.get("detail", "Bilinmeyen hata")
        return f"❌ *FAZ-6 KUPON HATASI*\n{detail}"

    result = engine_result.get("result", {})
    preds: List[Dict[str, Any]] = (
        result.get("portfolio")
        or result.get("predictions")
        or []
    )

    if not preds:
        return "⚠ Kupon oluşturmak için yeterli maç bulunamadı."

    preds = preds[: max_coupons * 3]
    coupons: List[List[Dict[str, Any]]] = [
        preds[i : i + 3] for i in range(0, len(preds), 3)
    ]
    coupons = coupons[:max_coupons]

    lines: List[str] = []
    lines.append("🎟 *FAZ-6 KUPONLARI*\n")

    for idx, coupon in enumerate(coupons, start=1):
        lines.append(f"🔥 *Kupon {idx}*")
        total_stake = 0.0

        for p in coupon:
            stake = float(p.get("recommended_stake", 1.0))
            total_stake += stake
            lines.append(
                f"- {p.get('id')} | {p.get('pick')} ({p.get('market')})\n"
                f"  Güven: {p.get('confidence')} | "
                f"Edge: {p.get('edge')} | "
                f"Stake: {stake}"
            )

        lines.append(f"💰 Toplam Stake: {round(total_stake, 2)}\n")

    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3800] + "\n… (çıktı kısaltıldı)"
    return text


__all__ = ["run_faz6_engine", "build_coupon_message"]
