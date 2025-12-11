import math
import statistics
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List


# ================================================================
# 🧱 DATA MODELLERİ
# ================================================================
@dataclass
class Faz13Input:
    source: str                      # "manual" / "api" / "visual" / "hybrid"
    manual_text: Optional[str] = None
    api_data: Optional[Dict[str, Any]] = None
    visual_meta: Optional[Dict[str, Any]] = None
    market_data: Optional[Dict[str, Any]] = None
    profile: Optional[Dict[str, Any]] = None


@dataclass
class ScoreBand:
    min: int
    max: int


@dataclass
class TotalPointsPrediction:
    value: float
    delta: float


@dataclass
class Faz13Prediction:
    score_band: ScoreBand
    total_points: TotalPointsPrediction
    side: Optional[str] = None      # "HOME", "AWAY", "NONE"


@dataclass
class Faz13RiskProfile:
    global_score: float             # 0-1 arası
    variance_level: str             # "LOW" / "MEDIUM" / "HIGH"
    confidence: int                 # 0-100


@dataclass
class Faz13Result:
    meta: Dict[str, Any]
    prediction: Dict[str, Any]
    risk: Dict[str, Any]
    raw_features: Dict[str, Any]


# ================================================================
# 🔧 NORMALİZASYON FONKSİYONLARI (FAZ-13)
# ================================================================
def normalize_manual_text(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    cleaned = " ".join(text.split())
    lowered = cleaned.lower()

    return {
        "raw": text,
        "cleaned": cleaned,
        "tokens": cleaned.split(),
        "has_overtime": "ot" in lowered or "uzatma" in lowered,
    }


def normalize_api_data(api_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not api_data:
        return None

    out = dict(api_data)
    if "pace" in out:
        try:
            out["pace"] = float(out["pace"])
        except Exception:
            pass
    if "off_rating_home" in out and "off_rating_away" in out:
        out["off_rating_diff"] = (
            float(out["off_rating_home"]) - float(out["off_rating_away"])
        )
    return out


def normalize_visual_meta(visual_meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not visual_meta:
        return None

    out = dict(visual_meta)
    # Buraya scoreboard / periyot skorları / son 5 maç vs. normalize edebilirsin
    return out


# ================================================================
# 🔮 FAZ-13 ANA PIPELINE
# ================================================================
def _estimate_base_total_points(data: Faz13Input) -> float:
    """
    Basit, placeholder bir total tahmini.
    Sen bunu kendi istatistik formüllerinle değiştireceksin.
    """
    base = 170.0

    if data.api_data:
        pace = float(data.api_data.get("pace", 95))
        off_h = float(data.api_data.get("off_rating_home", 110))
        off_a = float(data.api_data.get("off_rating_away", 108))
        base = (off_h + off_a) * (pace / 100.0) * 0.5

    if data.market_data and "main_total" in data.market_data:
        try:
            market_total = float(data.market_data["main_total"])
            base = (base * 0.6) + (market_total * 0.4)
        except Exception:
            pass

    return base


def _build_risk_profile(data: Faz13Input, base_total: float) -> Faz13RiskProfile:
    """
    FAZ-13 risk profili: ileride FAZ-9.x varyans motoru ile beslenebilir.
    Şimdilik basit placeholder mantık.
    """
    variance_level = "MEDIUM"
    global_score = 0.65
    confidence = 72

    if data.market_data:
        move = abs(float(data.market_data.get("line_move", 0.0)))
        if move > 4.0:
            variance_level = "HIGH"
            global_score = 0.55
            confidence = 60
        elif move < 1.5:
            variance_level = "LOW"
            global_score = 0.75
            confidence = 82

    return Faz13RiskProfile(
        global_score=global_score,
        variance_level=variance_level,
        confidence=confidence,
    )


def run_faz13_auto_pipeline(
    *,
    source: str,
    manual_text: Optional[Dict[str, Any]],
    api_data: Optional[Dict[str, Any]],
    visual_meta: Optional[Dict[str, Any]],
    market_data: Optional[Dict[str, Any]],
    profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    FAZ-13 tüm kaynakları tek yerde birleştirir, skor bandı + risk profili üretir.
    Dönen yapı main.py içinde bozulmadan kullanılacak şekilde tasarlandı.
    """
    data = Faz13Input(
        source=source,
        manual_text=manual_text,
        api_data=api_data,
        visual_meta=visual_meta,
        market_data=market_data,
        profile=profile,
    )

    base_total = _estimate_base_total_points(data)
    delta = 6.0  # dar bant için +/- 6 sayı → 12 sayılık band

    prediction = Faz13Prediction(
        score_band=ScoreBand(
            min=int(round(base_total - delta)),
            max=int(round(base_total + delta)),
        ),
        total_points=TotalPointsPrediction(
            value=round(base_total, 1),
            delta=delta,
        ),
        side=None,  # Taraf seçimi şimdilik boş, sen dolduracaksın
    )

    risk = _build_risk_profile(data, base_total)

    meta = {
        "league": (data.api_data or {}).get("league"),
        "tipoff": (data.api_data or {}).get("tipoff"),
        "source": source,
    }

    raw_features = {
        "manual": manual_text,
        "api": api_data,
        "visual": visual_meta,
        "market": market_data,
        "profile": profile,
    }

    result = Faz13Result(
        meta=meta,
        prediction={
            "score_band": asdict(prediction.score_band),
            "total_points": asdict(prediction.total_points),
            "side": prediction.side,
        },
        risk=asdict(risk),
        raw_features=raw_features,
    )

    return {
        "meta": result.meta,
        "prediction": result.prediction,
        "risk": result.risk,
        "raw_features": result.raw_features,
    }


# ================================================================
# 🎫 FAZ-13 KLASİK GÜNLÜK KUPON ÜRETİCİ
# ================================================================
def faz13_daily_coupon(faz13_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-13 klasik kupon şablonu.
    FAZ-23 yoksa main.py buraya düşecek.
    """
    pred = faz13_result.get("prediction", {})
    tp = pred.get("total_points", {})
    main_total = tp.get("value")

    if main_total is None:
        return {"legs": []}

    legs = [
        {
            "market": "Maç Sonu Toplam Sayı",
            "pick": "ÜST" if main_total >= 165 else "ALT",
            "line": round(main_total, 1),
            "risk_tag": "BASE",
        }
    ]

    return {"legs": legs}


# ================================================================
# 🧠 FAZ-23 META ENGINE
# ================================================================
def run_faz23_meta_engine(
    *,
    faz13_result: Dict[str, Any],
    market_data: Optional[Dict[str, Any]],
    profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    FAZ-23: FAZ-13 sonucunu + market verisini birlikte okuyup
    risk profilini keskinleştiren meta katman.

    Buradaki matematiği istediğin kadar hardcore yapabilirsin; yapı sabit.
    """
    risk = faz13_result.get("risk", {})
    pred = faz13_result.get("prediction", {})
    tp = pred.get("total_points", {}) or {}

    base_conf = float(risk.get("confidence", 70))
    global_score = float(risk.get("global_score", 0.65))
    market_total = None

    if market_data and "main_total" in market_data:
        try:
            market_total = float(market_data["main_total"])
        except Exception:
            market_total = None

    # Basit market alignment metriği
    alignment = 70.0
    if market_total is not None and tp.get("value") is not None:
        diff = abs(market_total - float(tp["value"]))
        alignment = max(0.0, 100.0 - diff * 4.0)

    # Sharpened risk:
    # - alignment yüksekse güveni yukarı çek
    # - alignment düşükse düşür
    sharpen_factor = (alignment / 100.0)
    sharpened_conf = int(round(base_conf * (0.7 + 0.6 * sharpen_factor)))
    sharpened_conf = max(0, min(100, sharpened_conf))

    sharpened_global = global_score * (0.8 + 0.4 * sharpen_factor)

    filter_mode = "NEUTRAL"
    if alignment >= 85 and sharpened_conf >= 80:
        filter_mode = "AGGRESSIVE_SAFE"
    elif alignment <= 60 or sharpened_conf <= 60:
        filter_mode = "ULTRA_CONSERVATIVE"

    return {
        "market_alignment": round(alignment, 1),
        "sharpened_confidence": sharpened_conf,
        "sharpened_risk": round(sharpened_global, 3),
        "filter_mode": filter_mode,
        "ref": {
            "base_confidence": base_conf,
            "base_global_score": global_score,
            "market_total": market_total,
            "model_total": tp.get("value"),
        },
    }


# ================================================================
# 🎫 FAZ-23 GÜVENLİ KUPON SEÇİCİ
# ================================================================
def build_faz23_safe_coupon(faz23_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-23 çıktılarına göre kupon filtresi.
    İster tek maç, ister paket kupon üret, yapı aynı kalacak.
    """
    filter_mode = faz23_result.get("filter_mode")
    alignment = faz23_result.get("market_alignment", 70.0)
    sharpened_conf = faz23_result.get("sharpened_confidence", 70)

    legs: List[Dict[str, Any]] = []

    # Örnek politika:
    # - alignment + confidence çok yüksek → ana barem civarı dar bant
    # - ortalama → 5–6 sayı güvenli bant kaydır
    # - düşük → sadece çok garanti görülen side / alt seç
    if filter_mode == "AGGRESSIVE_SAFE" and sharpened_conf >= 80:
        legs.append({
            "market": "Toplam Sayı (dar bant)",
            "pick": "MODEL_BAND",
            "line": "model band ±2",
            "risk_tag": "FAZ23_A",
        })
    elif filter_mode == "ULTRA_CONSERVATIVE":
        legs.append({
            "market": "Toplam Sayı (geniş bant)",
            "pick": "SAFE_ZONE",
            "line": "model band ±10",
            "risk_tag": "FAZ23_SAFE",
        })
    else:
        legs.append({
            "market": "Toplam Sayı",
            "pick": "BASE",
            "line": "model total",
            "risk_tag": "FAZ23_BASE",
        })

    return {"legs": legs}
