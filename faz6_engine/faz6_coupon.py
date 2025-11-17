from __future__ import annotations

from typing import Any, Dict, List


EngineResult = Dict[str, Any]
Prediction = Dict[str, Any]


# ================================================================
#        FAZ-6 KUPON ÜRETİCİ – TELEGRAM İÇİN FORMATLAYICI
# ================================================================


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_predictions(engine_result: EngineResult) -> List[Prediction]:
    """
    Hem eski hem yeni FAZ-6 çıktı formatlarıyla uyumlu prediction çıkarıcı.

    Desteklenen yapılar:
        - {"status": "ok", "mode": "...", "result": {"predictions": [...], ...}}
        - {"status": "ok", "mode": "...", "result": {"portfolio": [...], ...}}
        - {"status": "ok", "mode": "balance", "portfolio": [...], ...}
        - {"mode": "...", "predictions": [...], ...}
    """
    if not isinstance(engine_result, dict):
        return []

    # Önce 'result' içinden dene
    payload = engine_result.get("result")
    if isinstance(payload, dict):
        preds = payload.get("predictions") or payload.get("portfolio") or []
        if isinstance(preds, list):
            return preds

    # Sonra doğrudan üst seviyeden dene (eski format)
    preds = engine_result.get("predictions") or engine_result.get("portfolio") or []
    if isinstance(preds, list):
        return preds

    return []


def _normalize_match_label(p: Prediction) -> str:
    """
    Kupon satırında maç ismini üretir.
    """
    match = p.get("match")
    if match:
        return str(match)

    home = p.get("home_team") or p.get("home")
    away = p.get("away_team") or p.get("away")

    if home or away:
        return f"{home or '?'} - {away or '?'}"

    return str(p.get("id") or "Maç")


def _format_percent_like(value: Any) -> str:
    """
    confidence / edge gibi 0–1 veya 0–100 gelebilecek alanları
    görece düzgün insan formatına çevirir.
    """
    f = _to_float(value, default=-1.0)
    if f < 0:
        return "?"
    # 0–1 aralığı ise %'ye çevir
    if 0.0 <= f <= 1.5:
        return f"{f * 100:.1f}%"
    # Zaten yüzde gibi ise direkt yaz
    return f"{f:.1f}"


def _score_for_coupon_sort(p: Prediction) -> float:
    """
    Kupon için sıralama skoru:
        0.7 * edge  +  0.3 * confidence
    """
    edge = _to_float(p.get("edge"), 0.0)
    conf = _to_float(p.get("confidence"), 0.0)
    return edge * 0.7 + conf * 0.3


def _chunk_predictions(
    preds: List[Prediction],
    max_coupons: int,
    max_events_per_coupon: int,
) -> List[List[Prediction]]:
    """
    Tahminleri kuponlara böler:
        - max_coupons kadar kupon
        - her kupon max_events_per_coupon maç
    """
    limited = preds[: max_coupons * max_events_per_coupon]
    coupons: List[List[Prediction]] = []

    for i in range(0, len(limited), max_events_per_coupon):
        coupons.append(limited[i : i + max_events_per_coupon])

    return coupons[:max_coupons]


def build_coupon_message(
    engine_result: EngineResult,
    max_coupons: int = 3,
    max_events_per_coupon: int = 4,
) -> str:
    """
    FAZ-6 çıktı objesinden (safe_run_faz6_engine sonucu) Telegram kupon mesajı üretir.

    Beklenen giriş: main.py içindeki
        result = safe_run_faz6_engine(mode="balance")
    ile tamamen uyumludur.
    """
    if not isinstance(engine_result, dict):
        return "❌ *FAZ-6 KUPON HATA*\nGeçersiz motor çıktısı (dict değil)."

    status = engine_result.get("status", "ok")
    if status != "ok":
        detail = engine_result.get("detail") or repr(engine_result)
        return f"❌ *FAZ-6 KUPON HATA*\nMotor hatalı döndü:\n{detail}"

    preds = _extract_predictions(engine_result)

    if not preds:
        return (
            "⚠️ *FAZ-6 KUPON ÜRETİLEMEDİ*\n"
            "Motor çıktı döndürdü ama geçerli tahmin bulunamadı.\n"
            "• Canlı maç / market yok olabilir\n"
            "• Veya filtreler tüm seçimleri eledi"
        )

    # Tahminleri skorlayıp sırala (en iyi üstte)
    sorted_preds = sorted(preds, key=_score_for_coupon_sort, reverse=True)

    # Kuponlara böl
    coupons = _chunk_predictions(
        sorted_preds,
        max_coupons=max_coupons,
        max_events_per_coupon=max_events_per_coupon,
    )

    if not coupons:
        return (
            "⚠️ *FAZ-6 KUPON ÜRETİLEMEDİ*\n"
            "Filtre sonrası kupona girecek yeterli maç kalmadı."
        )

    text_lines: List[str] = []
    text_lines.append("🎫 *FAZ-6 Kupon Paketi*\n")

    mode = str(engine_result.get("mode") or "").upper()
    if mode:
        text_lines.append(f"🧠 Mod: {mode}\n")

    # Meta bilgisi varsa çok kısaca ekleyebiliriz (opsiyonel)
    result_block = engine_result.get("result") or {}
    meta = result_block.get("meta") or {}
    total_collected = meta.get("total_collected")
    total_selected = meta.get("total_selected")
    if isinstance(total_collected, int) and isinstance(total_selected, int):
        text_lines.append(
            f"📊 Toplanan maç: {total_collected} | Seçilen: {total_selected}\n"
        )

    text_lines.append("— — —\n")

    # Kuponları yaz
    for idx, coupon in enumerate(coupons, start=1):
        text_lines.append(f"💥 *Kupon {idx}*\n")

        for p in coupon:
            match_label = _normalize_match_label(p)
            pick = p.get("pick") or p.get("selection") or "Seçim yok"
            market = p.get("market") or "Market?"
            odds = p.get("odds") or p.get("price") or p.get("line") or "?"

            conf_txt = _format_percent_like(p.get("confidence"))
            edge_txt = _format_percent_like(p.get("edge"))
            stake = p.get("recommended_stake") or p.get("stake") or "-"

            league = p.get("league") or ""
            kickoff = p.get("kickoff") or p.get("start_time") or ""

            # Maç başlığı
            line = f"• {match_label}"
            if league:
                line += f" ({league})"
            text_lines.append(line)

            # Market + oran
            text_lines.append(f"  🎯 {pick} — {market} @ {odds}")

            # Güven / edge / stake
            text_lines.append(
                f"  📈 Güven: {conf_txt} | Edge: {edge_txt} | Stake: {stake}"
            )

            if kickoff:
                text_lines.append(f"  ⏰ {kickoff}")

            text_lines.append("")  # boş satır

        text_lines.append("— — —\n")

    msg = "\n".join(text_lines).strip()

    # Telegram karakter limiti için güvenlik
    if len(msg) > 3800:
        msg = msg[:3800] + "\n… (kupon listesi kısaltıldı)"

    return msg
```0
