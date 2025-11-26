import time
import math
from flask import Flask, jsonify

# ================================================================
# 🔥 HoopBrain Live API Backend (Simüle / Hook-Ready)
#  - NBA / EuroLeague / TR BSL / FIBA Europe
#  - Basit ama deterministik "fake live" motoru
#  - Sonra istersen gerçek API'lerle doldururuz
# ================================================================

app = Flask(__name__)


# ================================================================
# 🧮 Basit Simülasyon Motoru
# ================================================================
def _phase_from_time() -> tuple[str, str]:
    """
    Global fake clock:
      - 0–600 sn  → Q1
      - 600–1200 → Q2
      - 1200–1800→ Q3
      - 1800–2400→ Q4
      - >2400    → FT
    """
    base = int(time.time() // 10)  # 10sn tick
    t = base % 2600

    if t < 600:
        period = "Q1"
        rem = 600 - t
    elif t < 1200:
        period = "Q2"
        rem = 1200 - t
    elif t < 1800:
        period = "Q3"
        rem = 1800 - t
    elif t < 2400:
        period = "Q4"
        rem = 2400 - t
    else:
        period = "FT"
        rem = 0

    mm = rem // 60
    ss = rem % 60
    clock = f"{mm:02d}:{ss:02d}" if period != "FT" else "0:00"
    return period, clock


def _score_progress(base_total: float) -> float:
    """
    0–2400 saniye arasında toplam skorun yavaş yavaş artması.
    basit sigmoid/tanh eğrisi.
    """
    t = (time.time() % 2400) / 2400.0  # 0–1
    # t=0'da düşük, t=1'e yaklaşırken base_total civarına yaklaşsın
    return base_total * (0.15 + 0.9 * (1 - math.cos(math.pi * t)) / 2)


def _fake_live_core(league: str, home: str, away: str) -> dict:
    """
    Lig + takımlar bazlı basit skor / tempo / win_prob simülatörü
    """
    league = league.upper()
    home = home.upper()
    away = away.upper()

    # Lig bazlı tempo/total ayarı
    if league == "NBA":
        base_total = 225.0
        pace = 98.0
    elif league == "EL":
        base_total = 160.0
        pace = 78.0
    elif league == "TR":
        base_total = 165.0
        pace = 80.0
    elif league == "EU":
        base_total = 155.0
        pace = 76.0
    else:
        base_total = 170.0
        pace = 80.0

    period, clock = _phase_from_time()
    progress_total = _score_progress(base_total)

    # Home / away paylaşımı %55 / %45 gibi
    home_raw = progress_total * 0.55
    away_raw = progress_total * 0.45

    # Biraz noise katalım
    noise = int((time.time() // 30) % 7) - 3  # -3..+3
    home_score = max(0, int(home_raw + noise))
    away_score = max(0, int(away_raw - noise))

    # Win probability (çok basit)
    diff = home_score - away_score
    if period == "FT":
        if diff > 0:
            win_prob = 0.99
            win_side = "HOME"
        elif diff < 0:
            win_prob = 0.01
            win_side = "AWAY"
        else:
            win_prob = 0.50
            win_side = "HOME"
    else:
        # logistic
        win_raw = 1 / (1 + math.exp(-diff / 8.0))
        win_prob = float(round(0.1 + 0.8 * win_raw, 3))
        win_side = "HOME" if win_prob >= 0.5 else "AWAY"

    status = "IN_PROGRESS" if period != "FT" else "FINAL"

    return {
        "home_name": home,
        "away_name": away,
        "home_score": home_score,
        "away_score": away_score,
        "period_label": period,
        "clock": clock,
        "status": status,
        "pace": float(round(pace, 1)),
        "win_prob": win_prob,
        "win_side": win_side,
        "provider": f"HoopBrain-Sim-{league}",
    }


# ================================================================
# 🌍 LİG BAZLI ENDPOINTLER
# ================================================================
@app.get("/nba/live/<home>/<away>")
def nba_live(home, away):
    data = _fake_live_core("NBA", home, away)
    return jsonify(data), 200


@app.get("/el/live/<home>/<away>")
def el_live(home, away):
    data = _fake_live_core("EL", home, away)
    return jsonify(data), 200


@app.get("/tr/live/<home>/<away>")
def tr_live(home, away):
    data = _fake_live_core("TR", home, away)
    return jsonify(data), 200


@app.get("/eu/live/<home>/<away>")
def eu_live(home, away):
    data = _fake_live_core("EU", home, away)
    return jsonify(data), 200


@app.get("/")
def root():
    return "HoopBrain Live API OK", 200


# ================================================================
# 🚀 LOCAL / FLY.IO ENTRYPOINT
# ================================================================
if __name__ == "__main__":
    # Local test için: python live_api_main.py
    port = int(__import__("os").getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
