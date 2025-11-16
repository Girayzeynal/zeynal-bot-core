from typing import Dict, Any, List


def _normalize_engine_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    FAZ-6 motorundan gelen ham sonucu normalize eder.
    Hata durumunda detay yoksa, tüm result'u metinle görebilelim diye.
    """
    if not isinstance(result, dict):
        return {
            "status": "error",
            "detail": f"Geçersiz sonuç tipi: {type(result).__name__}",
            "raw": result,
        }

    status = result.get("status", "ok")
    detail = result.get("detail")

    if status != "ok" and not detail:
        detail = f"Detay yok. Ham sonuç: {repr(result)}"

    normalized = dict(result)
    normalized["status"] = status
    normalized["detail"] = detail
    return normalized


def build_coupon_message(engine_result: Dict[str, Any], max_coupons: int = 3) -> str:
    """
    FAZ-6 engine_result çıktısından, max_coupons adet kupon metni üretir.
    """
    data = _normalize_engine_result(engine_result)

    if data["status"] != "ok":
        detail = data.get("detail") or "Bilinmeyen hata"
        return f"❌ *FAZ-6 KUPON HATASI*\n{detail}"

    output = data.get("result", {})
    preds: List[Dict[str, Any]] = output.get("portfolio") or output.get("predictions") or []

    if not preds:
        return "⚠️ Kupon oluşturmak için uygun seçim bulunamadı."

    # En iyi max_coupons adet seçimi al
    selected = preds[:max_coupons]

    text = "🧾 *FAZ-6 KUPON ÖNERİSİ*\n\n"
    for idx, p in enumerate(selected, start=1):
        text += (
            f"#{idx}\n"
            f"📌 {p.get('id')}\n"
            f"🎯 {p.get('pick')} ({p.get('market')})\n"
            f"📈 Güven: {p.get('confidence')} | Edge: {p.get('edge')}\n"
            f"💰 Stake: {p.get('recommended_stake')}\n"
            f"— — —\n"
        )

    return text
