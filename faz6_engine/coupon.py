# ================================================================
#                 FAZ-6 KUPON MOTORU (3 KUPON)
# ================================================================

from __future__ import annotations
from typing import Dict, Any, List, Tuple


Prediction = Dict[str, Any]


def _extract_predictions(result: Dict[str, Any]) -> List[Prediction]:
    """
    FAZ-6 engine çıktısından maç listesini çıkarır.
    balance -> result['portfolio']
    diğer modlar -> result['predictions']
    """
    if not isinstance(result, dict):
        return []

    inner = result.get("result", {})
    if not isinstance(inner, dict):
        return []

    preds = inner.get("portfolio") or inner.get("predictions") or []
    if not isinstance(preds, list):
        return []

    out: List[Prediction] = []
    for p in preds:
        if isinstance(p, dict):
            out.append(p)
    return out


def _classify_tier(p: Prediction) -> str:
    """
    Maçı Tier S / A / B / C seviyesine ayır.
    """
    conf = float(p.get("confidence", 0.0) or 0.0)
    edge = float(p.get("edge", 0.0) or 0.0)

    if conf >= 0.70 and edge >= 0.06:
        return "S"
    if conf >= 0.65 and edge >= 0.04:
        return "A"
    if conf >= 0.60 and edge >= 0.02:
        return "B"
    return "C"


def _sort_by_stake(preds: List[Prediction]) -> List[Prediction]:
    return sorted(
        preds,
        key=lambda p: float(p.get("recommended_stake", 0.0) or 0.0),
        reverse=True,
    )


def _build_coupons(
    preds: List[Prediction],
    max_coupons: int = 3,
) -> Tuple[List[List[Prediction]], int]:
    """
    Tahmin listesini max_coupons adet kupona böler.
    Geri kalan maç sayısını da döndürür.
    """
    tiers = {"S": [], "A": [], "B": [], "C": []}
    for p in preds:
        tier = _classify_tier(p)
        q = dict(p)
        q["tier"] = tier
        tiers[tier].append(q)

    # Tier içlerini stake'e göre sırala
    for k in tiers:
        tiers[k] = _sort_by_stake(tiers[k])

    coupons: List[List[Prediction]] = [[] for _ in range(max_coupons)]

    # Kupon 1: S + A
    coupons[0].extend(tiers["S"])
    remaining_A = tiers["A"][:]
    coupons[0].extend(remaining_A[: max(0, 5 - len(coupons[0]))])
    remaining_A = remaining_A[max(0, 5 - len(coupons[0])) :]

    # Kupon 2: kalan A + güçlü B
    remaining_B = tiers["B"][:]
    coupons[1].extend(remaining_A)
    strong_B = [p for p in remaining_B if p.get("tier") == "B"]
    coupons[1].extend(strong_B[: max(0, 6 - len(coupons[1]))])

    # Kupon 3: kalan B (varsa)
    used_in_coupon2 = set(id(p) for p in strong_B[: max(0, 6 - len(remaining_A))])
    leftover_B = [p for p in remaining_B if id(p) not in used_in_coupon2]
    coupons[2].extend(leftover_B[:6])

    # Kuponlara girmeyenler:
    used = set()
    for c in coupons:
        for p in c:
            used.add(id(p))

    filtered_out = 0
    for tier_name, lst in tiers.items():
        for p in lst:
            if id(p) not in used:
                filtered_out += 1

    # C tier tamamen kupon dışı
    filtered_out += len(tiers["C"])

    # Boş kuponları sondan kırp
    while coupons and not coupons[-1]:
        coupons.pop()

    return coupons, filtered_out


def _format_single_coupon(idx: int, matches: List[Prediction]) -> str:
    if not matches:
        return ""

    header = f"🎟 *Kupon {idx}*  _(toplam {len(matches)} maç)_\n"
    lines = [header]

    for p in matches:
        match_id = p.get("id", "N/A")
        pick = p.get("pick", "N/A")
        market = p.get("market", "")
        conf = p.get("confidence", 0.0)
        edge = p.get("edge", 0.0)
        stake = p.get("recommended_stake", 0.0)
        tier = p.get("tier", "?")

        lines.append(
            f"📌 {match_id}  *(Tier {tier})*\n"
            f"🎯 {pick} ({market})\n"
            f"📈 Güven: {conf:.2f} | Edge: {edge:.3f}\n"
            f"💰 Stake: {stake:.3f}\n"
            f"— — —"
        )

    return "\n".join(lines) + "\n"


def build_coupon_message(faz6_result: Dict[str, Any], max_coupons: int = 3) -> str:
    """
    FAZ-6 balance çıktısından Telegram için kupon mesajı üretir.
    """
    if not isinstance(faz6_result, dict):
        return "❌ FAZ-6 KUPON: Geçersiz sonuç yapısı."

    if faz6_result.get("status") != "ok":
        detail = faz6_result.get("detail") or "Bilinmeyen hata"
        return f"❌ *FAZ-6 KUPON HATASI*\n{detail}"

    preds = _extract_predictions(faz6_result)
    if not preds:
        return "❌ FAZ-6 KUPON: Kullanılabilir seçim bulunamadı."

    coupons, filtered_out = _build_coupons(preds, max_coupons=max_coupons)

    text_lines = []
    text_lines.append("🧠 *FAZ-6 KUPON ÇIKTISI*\n_balance modundan türetilmiştir._\n")

    for idx, c in enumerate(coupons, start=1):
        text_lines.append(_format_single_coupon(idx, c))

    if filtered_out > 0:
        text_lines.append(
            f"ℹ️ Kupon limitleri nedeniyle {filtered_out} seçim liste dışı bırakıldı."
        )

    full_text = "\n".join(text_lines)

    # Telegram limitine karşı güvenlik
    if len(full_text) > 3800:
        full_text = full_text[:3800] + "\n… (çıktı kısaltıldı)"

    return full_text
