# faz5_engine_main.py
# FAZ-5 Heavy Engine Ana Motor
#
# Görev:
# - FAZ-4'ten NBA maçlarını çeker
# - Her maç için basit ama tutarlı bir güç analizi yapar
# - Güven skoruna göre sıralı "heavy kupon" önerisi üretir
# - /heavy, /heavy_risk, /heavy_edge, /heavy_auto, /heavy_full komutları buraya gelir

from typing import List

from nba_fetcher import fetch_nba_live_games, fetch_nba_today_games
from nba_analyzer import analyze_live_games
from nba_models import NBAGameState, NBATeamStatsLite


# ---------------------------------------------------------
#  YARDIMCI: MAÇTAN BASİT GÜÇ & TEMPO ANALİZİ
# ---------------------------------------------------------

def _simple_eval_from_game(game: NBAGameState) -> dict:
    """
    NBAGameState için basit ama tutarlı analiz:
    - Skor ve tempo üzerinden güç farkı çıkarır
    - Kazanan adayı ve güven skoru üretir
    """

    hs: NBATeamStatsLite | None = game.home_stats
    aw: NBATeamStatsLite | None = game.away_stats

    if not hs or not aw:
        # İstatistik yoksa, sadece isim bazlı dummy analiz
        return {
            "game_id": game.game_id,
            "home": game.home_team,
            "away": game.away_team,
            "status": game.status,
            "score_est": None,
            "pace_est": None,
            "pick": "VERİ YOK",
            "confidence": 0.5,
            "reason": "Takım istatistikleri eksik.",
        }

    # Tahmini toplam skor
    score_est = hs.pts + aw.pts

    # Pace tahmini
    home_pace = hs.pace_est if hs.pace_est is not None else 100.0
    away_pace = aw.pace_est if aw.pace_est is not None else 100.0
    pace_est = round((home_pace + away_pace) / 2, 1)

    # Skor farkına göre güç
    diff = hs.pts - aw.pts
    if diff > 0:
        pick = game.home_team
    elif diff < 0:
        pick = game.away_team
    else:
        pick = "DENGELİ"

    # Güven skoru: tamamen basit ama tutarlı
    base_conf = abs(diff) / 20.0 + 0.55  # fark büyüdükçe artar
    confidence = max(0.55, min(0.98, base_conf))

    reason_parts = []
    reason_parts.append(f"Skor farkı: {diff:+.0f}")
    reason_parts.append(f"Tahmini tempo: {pace_est}")
    reason = " | ".join(reason_parts)

    return {
        "game_id": game.game_id,
        "home": game.home_team,
        "away": game.away_team,
        "status": game.status,
        "score_est": round(score_est, 1),
        "pace_est": pace_est,
        "pick": pick,
        "confidence": round(confidence, 2),
        "reason": reason,
    }


def _build_ticket(games: List[NBAGameState], mode: str = "standard") -> dict:
    """
    Verilen maç listesinden FAZ-5 Heavy kuponu üretir.
    Mode:
      - standard: en güvenli 2-3 maç
      - risk: daha yüksek tempo ve fark arar
      - edge: orta güven + ilginç eşleşmeler
      - auto: kendince en iyi karışımı seçer
      - full: gördüğü her mantıklı eşleşmeyi listeler
    """
    if not games:
        return {
            "mode": mode,
            "picks": [],
            "meta": {
                "note": "Maç listesi boş geldi, kupon üretilemedi."
            }
        }

    evals = [_simple_eval_from_game(g) for g in games]

    # Status önceliği: live > scheduled > finished
    status_weight = {"live": 3, "scheduled": 2, "finished": 1}
    for e in evals:
        st = (e["status"] or "").lower()
        e["_status_weight"] = status_weight.get(st, 0)

    # Önce güven skoru, sonra canlılık
    evals.sort(key=lambda x: (x["confidence"], x["_status_weight"]), reverse=True)

    # Mode'a göre seçim sayısı
    mode = (mode or "standard").lower()
    if mode == "risk":
        max_picks = min(5, len(evals))
    elif mode == "edge":
        max_picks = min(3, len(evals))
    elif mode == "auto":
        max_picks = min(4, len(evals))
    elif mode == "full":
        max_picks = len(evals)
    else:  # standard
        max_picks = min(3, len(evals))

    picks = evals[:max_picks]

    return {
        "mode": mode,
        "picks": picks,
        "meta": {
            "total_games": len(evals),
            "selected": len(picks),
        },
    }


def _format_ticket_text(ticket: dict) -> str:
    """
    Heavy Engine çıktısını Telegram'da gösterilecek metne çevirir.
    """
    mode = ticket.get("mode", "standard")
    picks = ticket.get("picks", [])
    meta = ticket.get("meta", {})

    mode_title_map = {
        "standard": "Standart",
        "risk": "Risk",
        "edge": "Edge",
        "auto": "Otomatik",
        "full": "Full Paket",
    }
    mode_title = mode_title_map.get(mode, mode.capitalize())

    if not picks:
        note = meta.get("note", "Uygun maç bulunamadı.")
        return (
            f"⚠️ FAZ-5 Heavy Engine – {mode_title} modu\n"
            f"Kupon üretilemedi.\n"
            f"Not: {note}"
        )

    header = f"🔱 FAZ-5 Heavy Engine – {mode_title} modu\n"
    header += f"Seçilen maç sayısı: {meta.get('selected', len(picks))} / Toplam analiz: {meta.get('total_games', len(picks))}\n"
    header += "————————————\n"

    body_lines = []
    for i, p in enumerate(picks, start=1):
        line = []
        line.append(f"{i}. 🏀 {p['home']} vs {p['away']}")
        if p.get("score_est") is not None:
            line.append(f"   🎯 Tahmini Toplam Skor: {p['score_est']}")
        if p.get("pace_est") is not None:
            line.append(f"   🏃 Tempo Tahmini: {p['pace_est']}")
        line.append(f"   ✅ Tahmini Kazanan: {p['pick']} (güven: {int(p['confidence'] * 100)}%)")
        line.append(f"   📌 Not: {p['reason']}")
        body_lines.append("\n".join(line))

    body = "\n\n".join(body_lines)

    footer = "\n————————————\n"
    footer += "📊 Alt Yapı: FAZ-4 canlı maç analizi kullanıldı.\n"
    footer += "Bu kupon test amaçlıdır; gerçek bahis kararı senin komutanım. ⚔️"

    return header + body + footer


# ---------------------------------------------------------
#  DIŞ ARAYÜZ: main.py BURAYI KULLANIYOR
# ---------------------------------------------------------

def run_heavy_engine(mode: str = "standard") -> str:
    """
    FAZ-5 Heavy Engine'i çalıştırır ve metin çıktısını döndürür.
    main.py'deki /heavy* komutları burayı çağırır.
    """
    try:
        # Önce canlı maçları dene
        games: List[NBAGameState] = fetch_nba_live_games()

        # Canlı yoksa bugünkü planlı maçlara bak
        if not games:
            games = fetch_nba_today_games()

        if not games:
            return (
                "⚠️ FAZ-5 Heavy Engine\n"
                "Şu anda analiz edilecek NBA maçı bulunamadı.\n"
                "Canlı veya planlı maç yok gibi görünüyor."
            )

        ticket = _build_ticket(games, mode=mode)
        text = _format_ticket_text(ticket)

        # Ek olarak ham analiz metnini de alalım (bilgilendirme amaçlı)
        try:
            analysis_text = analyze_live_games(games)
            text += "\n\n📎 Ek Ham Analiz (FAZ-4):\n"
            text += analysis_text
        except Exception:
            # Analyzer patlarsa Heavy yine de çalışsın
            pass

        return text

    except Exception as e:
        return f"❌ FAZ-5 Heavy Engine Hatası: {e}"


def main(mode: str = "standard"):
    """
    Eğer 'python -m faz5_engine.faz5_engine_main' ile çağrılırsa
    kullanılabilecek basit giriş noktası.
    """
    return run_heavy_engine(mode) 
