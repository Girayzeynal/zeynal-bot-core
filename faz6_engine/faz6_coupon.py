from __future__ import annotations
from typing import Dict, Any, List, Tuple

Prediction = Dict[str, Any]
ResultDict = Dict[str, Any]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_predictions(result: ResultDict | None) -> List[Prediction]:
    """
    FAZ-6 result sözlüğünden prediction listesini çıkarır.

    Desteklenen yapılar:
        result["result"]["predictions"]
        result["result"]["portfolio"]
        result["predictions"]
        result["portfolio"]
    """
    if not isinstance(result, dict):
        return []

    payload = result.get("result") or result.get("data") or result
    if not isinstance(payload, dict):
        return []

    preds = (
        payload.get("predictions")
        or payload.get("portfolio")
        or result.get("predictions")
        or result.get("portfolio")
        or []
    )

    if not isinstance(preds, list):
        return []

    return preds


def _score_prediction(p: Prediction) -> float:
    """
    Kupon için seçim sıralama skoru:
        - edge (%70 ağırlık)
        - confidence (%30 ağırlık)
    """
    edge = _safe_float(p.get("edge"), 0.0)
    conf = _safe_float(p.get("confidence"), 0.0)
    return edge * 0.7 + conf * 0.3


def _chunk_list(items: List[Prediction], max_coupons: int) -> List[List[Prediction]]:
    """
    Prediction listesini kuponlara böler.
    Örn: 10 maç, max_coupons=3 => 4-3-3 gibi paylaşılır.
    """
    if not items or max_coupons <= 0:
        return []

    n = len(items)
    base = n // max_coupons
    extra = n % max_coupons

    chunks: List[List[Prediction]] = []
    index = 0

    for i in range(max_coupons):
        size = base + (1 if i < extra else 0)
        if size <= 0:
            chunks.append([])
            continue
        chunk = items[index:index + size]
        chunks.append(chunk)
        index += size

    return chunks


def build_coupon_message(result: ResultDict, max_coupons: int = 3) -> str:
    """
    FAZ-6 sonucundan Telegram için kupon mesajı üretir.

    - result: run_faz6_engine(...) çıktısı
    - max_coupons: en fazla kaç kupon oluşturulacağı
    """
    preds = _extract_predictions(result)

    if not preds:
        status = result.get("status")
        detail = result.get("detail") or "FAZ-6 sonuçlarında maç bulunamadı."
        if status == "error":
            return f"❌ *FAZ-6 KUPON HATASI*\n{detail}"
        return "⚠️ Kupon oluşturmak için yeterli maç tahmini bulunamadı."

    # Skora göre sıralama (en iyi seçimler en öne)
    sorted_preds = sorted(preds, key=_score_prediction, reverse=True)

    # Çok fazla seçim olursa, güvenlik için kırp
    # Örn: kupon başına max 6 maç gibi.
    max_per_coupon = 6
    hard_limit = max_coupons * max_per_coupon
    sorted_preds = sorted_preds[:hard_limit]

    # Kuponlara böl
    coupons = _chunk_list(sorted_preds, max_coupons)
    coupons = [c for c in coupons if c]  # boş kuponları at

    if not coupons:
        return "⚠️ Kupon oluşturmak için uygun kombinasyon bulunamadı."

    mode = (result.get("mode") or result.get("result", {}).get("mode") or "").upper()
    if not mode:
        mode = "AUTO"

    text_lines: List[str] = []
    text_lines.append(f"🎫 *FAZ-6 {mode} KUPON PAKETİ*")
    text_lines.append("")
    text_lines.append(f"Toplam seçim: {len(sorted_preds)} | Kupon sayısı: {len(coupons)}")
    text_lines.append("")

    for idx, coupon in enumerate(coupons, start=1):
        text_lines.append(f"========================")
        text_lines.append(f"💼 *Kupon {idx}*")
        text_lines.append(f"Maç sayısı: {len(coupon)}")
        text_lines.append("")

        for p in coupon:
            match_id = p.get("id") or p.get("match") or p.get("code") or "N/A"
            league = p.get("league") or ""
            market = p.get("market") or p.get("type") or "market"
            pick = p.get("pick") or p.get("selection") or "SEÇİM YOK"

            conf = _safe_float(p.get("confidence"), 0.0)
            edge = _safe_float(p.get("edge"), 0.0)
            stake = p.get("recommended_stake")

            line = f"• {match_id}"
            if league:
                line += f" ({league})"
            text_lines.append(line)

            text_lines.append(f"   🎯 {pick} [{market}]")
            text_lines.append(
                f"   📈 Güven: {conf:.2f} | Edge: {edge:.2f}"
            )
            if stake is not None:
                text_lines.append(f"   💰 Stake: {stake}")
            text_lines.append("")

    message = "\n".join(text_lines)

    # Telegram 4096 karakter sınırı için güvenlik marjı
    if len(message) > 3800:
        message = message[:3800] + "\n… (kupon çıktısı kısaltıldı)"

    return message
