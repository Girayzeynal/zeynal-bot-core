from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
import re
import math
from datetime import datetime
import logging

log = logging.getLogger(__name__)

# ================================================================
# 🔌 FAZ-11 / FAZ-12 BAĞLANTISI
#   DİKKAT: main.py'den hiçbir şey import ETMİYORUZ → circular yok.
# ================================================================
from faz11_engine.faz11_feedback import faz11_last_summary
from faz12_engine.faz12_autoadjust import faz12_run_once


# ================================================================
# 🔹 FUSION INPUT – TEK STANDARD FORMAT
# ================================================================
@dataclass
class FusionInput:
    source: str          # "manual" | "api" | "visual" | ...
    league: str
    home: str
    away: str
    market: str          # "FT TOTAL", "FT SPREAD", vs.
    line: Optional[float]
    side: str            # "U" / "O" / "H" / "A" / ...
    odds: Optional[float]
    start_time: Optional[str] = None  # ISO string veya None
    meta: Dict[str, Any] = None       # ham payload, OCR text vs.

    def __post_init__(self):
        if self.meta is None:
            self.meta = {}


# ================================================================
# 🔧 KÜÇÜK YARDIMCI
# ================================================================
def _safe_float(x, default=None):
    try:
        if x is None:
            return default
        return float(str(x).replace(",", "."))
    except Exception:
        return default


# ================================================================
# 1️⃣ MANUEL KOMUT NORMALİZASYONU
#    Örn: /mac BOS ORL 220.5 U 1.46
# ================================================================
def normalize_manual_text(text: str, default_league: str = "NBA") -> FusionInput:
    raw = text.strip()
    parts = raw.split()

    if not parts:
        raise ValueError("Boş komut")

    # /mac'i düş
    if parts[0].startswith("/"):
        parts = parts[1:]

    if len(parts) < 5:
        raise ValueError("Beklenen format: /mac HOME AWAY LINE SIDE ORAN")

    home = parts[0].upper()
    away = parts[1].upper()
    line = _safe_float(parts[2])
    side = parts[3].upper()
    odds = _safe_float(parts[4])

    market = "FT TOTAL"  # şimdilik sabit – ileride genişletilebilir

    return FusionInput(
        source="manual",
        league=default_league,
        home=home,
        away=away,
        market=market,
        line=line,
        side=side,
        odds=odds,
        start_time=None,
        meta={"raw": raw},
    )


# ================================================================
# 2️⃣ API VERİSİ NORMALİZASYONU
#    Beklenen alanlar:
#      league, home, away, market, line, side, odds, start_time
# ================================================================
def normalize_api_data(match: Dict[str, Any]) -> FusionInput:
    league = str(match.get("league", "UNKNOWN"))
    home = str(match.get("home", "HOME")).upper()
    away = str(match.get("away", "AWAY")).upper()
    market = str(match.get("market", "FT TOTAL"))

    line = _safe_float(match.get("line"))
    side = str(match.get("side", "U")).upper()
    odds = _safe_float(match.get("odds"))
    start_time = match.get("start_time")  # ISO bekliyoruz

    return FusionInput(
        source=match.get("source", "api"),
        league=league,
        home=home,
        away=away,
        market=market,
        line=line,
        side=side,
        odds=odds,
        start_time=start_time,
        meta=match,
    )


# ================================================================
# 3️⃣ GÖRSEL / OCR NORMALİZASYONU
#    Buraya şimdilik text veriyoruz (OCR sonrası).
# ================================================================
def normalize_visual_meta(text: str, default_league: str = "NBA") -> FusionInput:
    raw = text

    # Olası takım kodları (3–4 harf)
    tokens = re.findall(r"[A-Z]{2,4}", text)

    # Sayısal değerler
    nums = re.findall(r"\d+[\.,]?\d*", text)

    odds_candidates = [n for n in nums if _safe_float(n, 0) >= 1.10]
    line_candidates = [n for n in nums if _safe_float(n, 0) < 1000]

    # Yön tespiti
    side = "U"
    if re.search(r"\b(U|ALT|UNDER)\b", text, re.IGNORECASE):
        side = "U"
    if re.search(r"\b(O|ÜST|OVER)\b", text, re.IGNORECASE):
        side = "O"

    home = tokens[0] if len(tokens) >= 1 else "HOME"
    away = tokens[1] if len(tokens) >= 2 else "AWAY"

    line = _safe_float(line_candidates[0]) if line_candidates else None
    odds = _safe_float(odds_candidates[-1]) if odds_candidates else None

    market = "FT TOTAL"

    return FusionInput(
        source="visual",
        league=default_league,
        home=home,
        away=away,
        market=market,
        line=line,
        side=side,
        odds=odds,
        start_time=None,
        meta={"raw_ocr": raw},
    )


# ================================================================
# 🎛 FAZ-13.1 DELUXE SKORLAYICI
#    – oran → implied prob
#    – lig / market / info kalitesi → conf & edge
#    – bucket + risk + score
# ================================================================
def _estimate_conf_edge_bucket(fi: FusionInput) -> Dict[str, Any]:
    # 1) implied probability
    if fi.odds:
        implied_p = 1.0 / fi.odds
        implied_p = max(0.30, min(implied_p, 0.80))
    else:
        implied_p = 0.55  # default

    # 2) base conf: 0.55–0.75 arası
    base_conf = 0.55 + (0.15 * (0.5 - abs(implied_p - 0.5)) / 0.5)
    # merkezi oranlarda (1.70–2.10) daha yüksek güven, uç oranlarda daha düşük

    # Lig bonusu
    if fi.league.upper() in ("NBA", "EUROLEAGUE", "EL"):
        base_conf += 0.02

    # Market cezası (period/quarter vs)
    if fi.market:
        m = fi.market.upper()
        if any(tag in m for tag in ("Q1", "Q2", "Q3", "Q4")):
            base_conf -= 0.02
        if "1. YARI" in m or "1.YARI" in m:
            base_conf -= 0.01

    # Kaynak kalitesi (manuel vs görsel vs api)
    src = fi.source.lower()
    if src == "manual":
        base_conf += 0.01  # senin filtre + gözlem
    if src == "visual":
        base_conf -= 0.02  # OCR/noise riski

    base_conf = max(0.50, min(base_conf, 0.78))

    # 3) edge = model_conf - implied_p
    edge = base_conf - implied_p

    # 4) bucket / risk sınıfları
    if base_conf >= 0.68 and edge >= 0.045:
        bucket = "HIGH"
    elif base_conf >= 0.60 and edge >= 0.02:
        bucket = "MID"
    else:
        bucket = "LOW"

    if bucket == "HIGH":
        risk = "HIGH"
    elif bucket == "LOW":
        risk = "LOW"
    else:
        risk = "MID"

    # 5) tek bir skor: conf ve edge karışımı
    score = base_conf * 100 + edge * 80

    return {
        "pred_conf": round(base_conf, 3),
        "pred_edge": round(edge, 3),
        "pred_bucket": bucket,
        "risk": risk,
        "implied_p": round(implied_p, 3),
        "score": round(score, 1),
    }


# ================================================================
# 🔁 FAZ-10/11/12 PIPELINE BAĞLANTI (lightweight)
#    – FAZ-11 son günlük özetini okur
#    – FAZ-12'ye "dummy f10_state" geçirir (stability ~ daily_acc)
# ================================================================
def _auto_faz_pipeline(
    pred_conf: float,
    pred_edge: float,
    pred_bucket: str,
    real_result=None,
) -> Dict[str, Any]:
    f11_state = None
    decision = None

    # FAZ-11 son kayıt
    try:
        summary = faz11_last_summary()
        f11_state = summary.get("last") or None
    except Exception as e:
        log.warning(f"[FAZ-13] FAZ-11 summary hatası: {e}")
        f11_state = None

    # FAZ-12 auto profile
    if f11_state:
        try:
            # FAZ-12'nin istediği tek şey: f10_state["stability"]
            f10_state = {"stability": float(f11_state.get("daily_accuracy", 0.7))}
            decision = faz12_run_once(f10_state, f11_state)
        except Exception as e:
            log.warning(f"[FAZ-13] FAZ-12 run hatası: {e}")
            decision = None

    return {
        "f11_last": f11_state,
        "f12_decision": decision,
        "pred_conf": float(pred_conf),
        "pred_edge": float(pred_edge),
        "pred_bucket": str(pred_bucket),
    }


# ================================================================
# 🧠 ANA SİNYAL HESAPLAYICI
# ================================================================
def compute_faz13_signal(fusion_input: FusionInput) -> Dict[str, Any]:
    est = _estimate_conf_edge_bucket(fusion_input)

    pipe = _auto_faz_pipeline(
        pred_conf=est["pred_conf"],
        pred_edge=est["pred_edge"],
        pred_bucket=est["pred_bucket"],
        real_result=None,
    )

    signal = {
        "fusion": asdict(fusion_input),
        "est": est,
        "pipeline": pipe,
    }
    return signal


# ================================================================
# 🧾 TEK MAÇ FORMATLAYICI (TELEGRAM HTML)
# ================================================================
def format_faz13_signal_html(signal: Dict[str, Any]) -> str:
    f = signal["fusion"]
    e = signal["est"]
    p = signal["pipeline"]

    league = f.get("league", "")
    home = f.get("home", "")
    away = f.get("away", "")
    market = f.get("market", "")
    line = f.get("line", "")
    side = f.get("side", "")
    odds = f.get("odds", "")

    mode = "-"
    if p.get("f12_decision"):
        mode = p["f12_decision"].get("new_mode", p["f12_decision"].get("prev_mode", "-"))

    text: List[str] = []

    text.append("🔥 <b>FAZ-13.1 Kupon Sinyali</b>")
    text.append("")
    text.append(f"🏷 <b>Lig:</b> {league}")
    text.append(f"🏀 <b>Maç:</b> {home} - {away}")
    text.append(f"🎯 <b>Pazar:</b> {market}")
    text.append(f"📏 <b>Line/Yön:</b> {line} / {side}")
    text.append(f"💰 <b>Oran:</b> {odds}")
    text.append("")
    text.append("📊 <b>Model Çıkışı</b>")
    text.append(f"• Conf: <b>{e['pred_conf']:.3f}</b>")
    text.append(f"• Edge: <b>{e['pred_edge']:.3f}</b>")
    text.append(f"• Bucket: <b>{e['pred_bucket']}</b> | Risk: <b>{e['risk']}</b>")
    text.append(f"• Implied P: {e['implied_p']:.3f}")
    text.append(f"• Score: {e['score']:.1f}")
    text.append("")
    text.append("🧠 <b>FAZ-11/12 Durumu</b>")
    if p["f11_last"]:
        text.append(f"• Son Gün Doğruluk: {p['f11_last'].get('daily_accuracy', '-')}")
        text.append(f"• Model Drift: {p['f11_last'].get('model_drift', '-')}")
    else:
        text.append("• FAZ-11 verisi yok.")
    if p["f12_decision"]:
        text.append(f"• Mode: <b>{mode}</b>")
        text.append(f"• Reason: {p['f12_decision'].get('reason', '-')}")
    else:
        text.append("• FAZ-12 kararı yok.")
    text.append("")
    text.append("✅ <b>Öneri:</b>")
    text.append(f"{home} - {away} | {market} {line} {side} @ {odds}")

    return "\n".join(text)


# ================================================================
# 🚀 TEK MAÇ PIPELINE ENTRY
# ================================================================
def run_faz13_auto_pipeline(fusion_input: FusionInput) -> str:
    signal = compute_faz13_signal(fusion_input)
    return format_faz13_signal_html(signal)


# ================================================================
# 📦 1) GÜNLÜK KUPON – TÜM MAÇ LİSTESİNDEN TOP PICKS
#    match_list: [{league, home, away, market, line, side, odds, start_time}, ...]
# ================================================================
def faz13_daily_coupon(match_list: List[Dict[str, Any]]) -> str:
    signals: List[Dict[str, Any]] = []

    for m in match_list:
        try:
            fi = normalize_api_data(m)
            sig = compute_faz13_signal(fi)
            signals.append(sig)
        except Exception as e:
            log.warning(f"[FAZ-13 DAILY] Maç atlandı: {e}")

    # Score'a göre sırala, ilk 8'i al
    signals.sort(key=lambda s: s["est"]["score"], reverse=True)
    top = signals[:8]

    out_lines: List[str] = ["🔥 <b>FAZ-13.1 Günlük Kupon</b>", ""]

    for idx, sig in enumerate(top, start=1):
        f = sig["fusion"]
        e = sig["est"]
        out_lines.append(
            f"#{idx}) {f['home']} - {f['away']} | {f['market']} {f['line']} {f['side']} @ {f['odds']}"
        )
        out_lines.append(
            f"   Conf={e['pred_conf']:.3f} Edge={e['pred_edge']:.3f} Bucket={e['pred_bucket']} Score={e['score']:.1f}"
        )

    return "\n".join(out_lines)


# ================================================================
# ⏱ 2) YAKLAŞAN MAÇ KUPONU
#    – start_time (ISO) alanı 0–minutes_before dk içindeyse
# ================================================================
def faz13_upcoming_coupon(
    match_list: List[Dict[str, Any]],
    minutes_before: int = 40,
) -> str:
    now = datetime.utcnow()
    cand: List[Dict[str, Any]] = []

    for m in match_list:
        st_raw = m.get("start_time")
        if not st_raw:
            continue

        try:
            start = datetime.fromisoformat(st_raw.replace("Z", "+00:00"))
        except Exception:
            continue

        diff_min = (start - now).total_seconds() / 60.0
        if 0 <= diff_min <= minutes_before:
            try:
                fi = normalize_api_data(m)
                sig = compute_faz13_signal(fi)
                sig["diff_min"] = diff_min
                cand.append(sig)
            except Exception as e:
                log.warning(f"[FAZ-13 UPCOMING] Maç atlandı: {e}")

    cand.sort(key=lambda s: s["est"]["score"], reverse=True)
    top = cand[:5]

    out: List[str] = ["⏱ <b>FAZ-13.1 Yaklaşan Maç Kuponu</b>", ""]

    for idx, sig in enumerate(top, start=1):
        f = sig["fusion"]
        e = sig["est"]
        mins = sig.get("diff_min", 0)
        out.append(f"#{idx}) {f['home']} - {f['away']} ({mins:.0f} dk kala)")
        out.append(
            f"   {f['market']} {f['line']} {f['side']} @ {f['odds']} | Conf={e['pred_conf']:.3f} Edge={e['pred_edge']:.3f}"
        )

    return "\n".join(out)


# ================================================================
# 🏷 3) LİG / ORGANİZASYON BAZLI KUPON
# ================================================================
def faz13_league_coupon(
    match_list: List[Dict[str, Any]],
    league_name: str,
) -> str:
    league_name_l = league_name.lower()
    signals: List[Dict[str, Any]] = []

    for m in match_list:
        if str(m.get("league", "")).lower() != league_name_l:
            continue
        try:
            fi = normalize_api_data(m)
            sig = compute_faz13_signal(fi)
            signals.append(sig)
        except Exception as e:
            log.warning(f"[FAZ-13 LEAGUE] Maç atlandı: {e}")

    signals.sort(key=lambda s: s["est"]["score"], reverse=True)
    top = signals[:10]

    out: List[str] = [f"🏷 <b>FAZ-13.1 Lig Kuponu</b> – {league_name}", ""]

    for idx, sig in enumerate(top, start=1):
        f = sig["fusion"]
        e = sig["est"]
        out.append(
            f"#{idx}) {f['home']} - {f['away']} | {f['market']} {f['line']} {f['side']} @ {f['odds']}"
        )
        out.append(
            f"   Conf={e['pred_conf']:.3f} Edge={e['pred_edge']:.3f} Bucket={e['pred_bucket']}"
        )

    return "\n".join(out)


# ================================================================
# 📡 4) CANLI MAÇ KUPONU
# ================================================================
def faz13_live_coupon(live_matches: List[Dict[str, Any]]) -> str:
    signals: List[Dict[str, Any]] = []

    for m in live_matches:
        try:
            fi = normalize_api_data(m)
            sig = compute_faz13_signal(fi)
            signals.append(sig)
        except Exception as e:
            log.warning(f"[FAZ-13 LIVE] Maç atlandı: {e}")

    signals.sort(key=lambda s: s["est"]["score"], reverse=True)
    top = signals[:8]

    out: List[str] = ["📡 <b>FAZ-13.1 Canlı Kupon</b>", ""]

    for idx, sig in enumerate(top, start=1):
        f = sig["fusion"]
        e = sig["est"]
        out.append(
            f"#{idx}) {f['home']} - {f['away']} | {f['market']} {f['line']} {f['side']} @ {f['odds']}"
        )
        out.append(
            f"   Conf={e['pred_conf']:.3f} Edge={e['pred_edge']:.3f} Bucket={e['pred_bucket']}"
        )

    return "\n".join(out)


# ================================================================
# 🖼 5) GÖRSEL / OCR TABANLI KUPON
#    Not: Burada OCR'ı dışarıda çalıştırıp text vereceğiz.
# ================================================================
def faz13_visual_coupon_from_text(ocr_text: str, default_league: str = "NBA") -> str:
    fi = normalize_visual_meta(ocr_text, default_league=default_league)
    return run_faz13_auto_pipeline(fi)
