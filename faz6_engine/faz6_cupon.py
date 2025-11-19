from __future__ import annotations

from typing import Any, Dict, List


Prediction = Dict[str, Any]


def _extract_predictions(result: Dict[str, Any]) -> List[Prediction]:
    if not isinstance(result, dict):
        return []

    block = result.get("result") or {}
    preds = block.get("predictions") or block.get("portfolio") or []
    if not isinstance(preds, list):
        return []
    return preds


def build_coupon_message(result: Dict[str, Any], max_coupons: int = 3) -> str:
    """
    FAZ-6 balance çıktısından basit kuponlar üretir.
    Şimdilik:
      - tüm tahminleri al
      - sırayla kuponlara böl (her kupon 2-3 maç)
    """
    status = result.get("status", "ok")
    if status != "ok":
        detail = result.get("detail") or "Bilinmeyen FAZ-6 hatası."
        return f"❌ *FAZ-6 KUPON HATA*\n{detail}"

    preds = _extract_predictions(result)
    if not preds:
        return "⚠️ FAZ-6 kupon oluşturmak için yeterli maç bulamadı."

    # Kupon başına 3 maç hedefleyelim
    per_coupon = 3
    coupons: List[List[Prediction]] = []
    current: List[Prediction] = []

    for p in preds:
        current.append(p)
        if len(current) == per_coupon:
            coupons.append(current)
            current = []
        if len(coupons) >= max_coupons:
            break

    if current and len(coupons) < max_coupons:
        coupons.append(current)

    if not coupons:
        return "⚠️ FAZ-6 kupon üretemedi."

    text_lines: List[str] = []
    text_lines.append("🎫 *FAZ-6 KUPONLAR*")
    text_lines.append("")

    for idx, coupon in enumerate(coupons, start=1):
        text_lines.append(f"✅ *Kupon {idx}*")
        total_stake = 0.0

        for p in coupon:
            cid = p.get("id", "UNKNOWN")
            pick = p.get("pick") or p.get("selection") or "YOK"
            market = p.get("market") or "market"
            conf = p.get("confidence")
            edge = p.get("edge")
            stake = p.get("recommended_stake") or 1.0
            total_stake += float(stake)

            text_lines.append(
                f"• {cid}\n"
                f"  🎯 {pick} ({market})\n"
                f"  📈 Güven: {conf} | Edge: {edge}\n"
                f"  💰 Stake: {stake}"
            )

        text_lines.append(f"🔢 Toplam Kupon Stake: {round(total_stake, 3)}")
        text_lines.append("— — —")

    return "\n".join(text_lines)
