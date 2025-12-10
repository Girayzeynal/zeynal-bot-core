import os
import time
import json
import traceback
import re

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

# ============================================================
# HOOPBRAIN PROXY — FAZ-23 + FAZ-13 UYUMLU ÇEKİRDEK
# ============================================================
app = FastAPI(
    title="HoopBrain Proxy",
    version="23.1",
    description="FAZ-23 + FAZ-13 için istatistik, barem, haber, live veri proxy çekirdek servisi."
)

# ------------------------------------------------------------
# GLOBAL RATE-LIMIT (60 req / 60 sec)
# ------------------------------------------------------------
REQ_LIMIT = 60
WINDOW = 60
req_times = []


def allow_request() -> bool:
    now = time.time()
    req_times.append(now)
    while req_times and req_times[0] < now - WINDOW:
        req_times.pop(0)
    return len(req_times) <= REQ_LIMIT


# ------------------------------------------------------------
# GENEL REQUEST FONKSİYONU (timeout + fail-safe)
# ------------------------------------------------------------
def fetch_url(url: str):
    try:
        if not allow_request():
            return {"error": "Rate limit exceeded"}

        r = requests.get(
            url,
            timeout=7,
            headers={
                "User-Agent": "Mozilla/5.0 (HoopBrain Proxy)"
            },
        )
        r.raise_for_status()
        return r.text
    except Exception as e:
        return {"error": str(e)}


# ------------------------------------------------------------
# YARDIMCI: TAKIM İSMİ NORMALİZE
# ------------------------------------------------------------
def norm_name(name: str) -> str:
    if not name:
        return ""
    return (
        name.lower()
        .replace("ş", "s")
        .replace("ı", "i")
        .replace("ö", "o")
        .replace("ü", "u")
        .replace("ç", "c")
        .replace("ğ", "g")
        .strip()
    )


# ------------------------------------------------------------
# YARDIMCI: LİGE GÖRE BASELINE TOTAL TAHMİNİ
# ------------------------------------------------------------
def guess_baseline_total(league: str) -> float:
    if not league:
        return 160.0

    l = league.lower()
    if "nba" in l:
        return 230.0
    if "euroleague" in l:
        return 162.0
    if "eurocup" in l:
        return 164.0
    if "bsln" in l or "bsl" in l or "türkiye" in l or "turkey" in l:
        return 162.0
    if "liga endesa" in l or "acb" in l:
        return 161.0
    if "aba" in l:
        return 163.0
    if "fiba" in l or "world cup" in l or "eurobasket" in l:
        return 170.0
    return 160.0


# ------------------------------------------------------------
# YARDIMCI: MACKOLIK PROGRAMDAN TOPLAM BAREM OKU
# (approx — FAZ-13 için ilk versiyon)
# ------------------------------------------------------------
def fetch_mackolik_program_total(league: str, home: str, away: str):
    try:
        url = "https://arsiv.mackolik.com/Program/Program.aspx?st=2"
        html = fetch_url(url)
        if isinstance(html, dict):
            return None, {"error": html.get("error")}

        soup = BeautifulSoup(html, "lxml")

        nh = norm_name(home)
        na = norm_name(away)

        best_line = None

        for row in soup.select("tr"):
            text = " ".join(row.stripped_strings)
            tnorm = norm_name(text)

            if nh and na and (nh in tnorm and na in tnorm):
                # satırda home-away ikilisi geçti, skor satırındayız
                # bu bloktan son görülen "xxx,yy" pattern'ini al
                candidates = re.findall(r"(\d{3},\d{1,2})", text)
                if candidates:
                    val = candidates[-1]  # satırın sağ tarafındaki TS genelde bu
                    try:
                        v = float(val.replace(",", "."))
                        best_line = v
                    except Exception:
                        pass

        if best_line is None:
            return None, {"info": "match_not_found"}

        return best_line, {"source": "mackolik_program"}
    except Exception as e:
        return None, {"error": str(e)}


# ------------------------------------------------------------
# YARDIMCI: GOOGLE NEWS'TEN TAKIM HABERLERİ
# ------------------------------------------------------------
def fetch_team_news(team: str, limit: int = 15):
    try:
        url = (
            "https://news.google.com/search?"
            f"q={team}+basketball&hl=tr&gl=TR&ceid=TR:tr"
        )
        html = fetch_url(url)
        if isinstance(html, dict):
            return [], html.get("error")

        soup = BeautifulSoup(html, "lxml")
        titles = [x.text.strip() for x in soup.select("h3")]
        return titles[:limit], None
    except Exception as e:
        return [], str(e)


# ------------------------------------------------------------
# ✔ 1) LIVE PROVIDERS (FAZ-23 çekirdek uyumlu)
# ------------------------------------------------------------
@app.get("/live")
def get_live(match_id: str = Query(...)):
    try:
        url = f"https://www.flashscore.com/match/{match_id}/#/match-summary"
        html = fetch_url(url)
        if isinstance(html, dict):
            return html

        soup = BeautifulSoup(html, "lxml")

        score = soup.select_one(".detailScore__wrapper")
        home = soup.select_one(".participant__home .participant__participantName")
        away = soup.select_one(".participant__away .participant__participantName")

        return {
            "match_id": match_id,
            "home": home.text.strip() if home else None,
            "away": away.text.strip() if away else None,
            "score": score.text.strip() if score else None,
        }
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}


# ------------------------------------------------------------
# ✔ 2) İSTATİSTİK / TAKIM FORM / H2H (FAZ-13 uyumlu)
# ------------------------------------------------------------
@app.get("/stats")
def get_stats(match_id: str = Query(...)):
    try:
        url = f"https://www.flashscore.com/match/{match_id}/#/h2h/overall"
        html = fetch_url(url)
        if isinstance(html, dict):
            return html

        soup = BeautifulSoup(html, "lxml")
        blocks = soup.select(".h2h__section")

        data = []
        for b in blocks:
            title = b.select_one(".section__title")
            table = b.select("tr")
            rows = []
            for row in table:
                cols = [c.text.strip() for c in row.select("td")]
                if cols:
                    rows.append(cols)

            data.append(
                {
                    "title": title.text.strip() if title else None,
                    "rows": rows,
                }
            )

        return {"match_id": match_id, "data": data}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}


# ------------------------------------------------------------
# ✔ 3) BAREM / MAÇ ÖNCESİ LİNE (iddaa – nesine – odds API)
# (şimdilik: Mackolik match-detay sayfasındaki odds blokları)
# ------------------------------------------------------------
@app.get("/barem")
def get_barems(match_id: str = Query(...)):
    try:
        url = f"https://www.mackolik.com/basketbol/mac-detay/{match_id}"
        html = fetch_url(url)
        if isinstance(html, dict):
            return html

        soup = BeautifulSoup(html, "lxml")
        odds = soup.select(".odds-item")
        lines = []

        for o in odds:
            t = o.text.strip().replace("\n", " ")
            if t:
                lines.append(t)

        return {"match_id": match_id, "baremler": lines}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}


# ------------------------------------------------------------
# ✔ 4) HABER / SON DAKİKA / KADRO BİLGİSİ (ham Google News)
# ------------------------------------------------------------
@app.get("/news")
def get_news(team: str = Query(...)):
    try:
        titles, err = fetch_team_news(team)
        if err:
            return {"team": team, "error": err}

        return {
            "team": team,
            "count": len(titles),
            "headlines": titles,
        }
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}


# ------------------------------------------------------------
# 🔥 5) FAZ-13 FULL AUTO NEWS ENDPOINT
# FAZ-13 -> /faz13/news ile çağırır, NewsSummary formatında cevap alır
# ------------------------------------------------------------
@app.get("/faz13/news")
def faz13_news(
    league: str = Query(...),
    date: str = Query(...),
    home: str = Query(...),
    away: str = Query(...),
):
    """
    FAZ-13 için FULL AUTO:
    - Mackolik Program'dan (yaklaşık) toplam barem (TS)
    - Google News'ten her iki takım için haber başlıkları
    - Baseline + barem + haberlerden soft skor bandı ve flag’ler
    """

    try:
        # 1) Baseline
        baseline = guess_baseline_total(league)

        # 2) Mackolik program baremi (varsa)
        book_total, barem_meta = fetch_mackolik_program_total(league, home, away)

        if book_total is None:
            main_total = baseline
            consensus = "BASELINE_ONLY"
        else:
            main_total = float(book_total)
            consensus = "BOOK_PROGRAM"

        # 3) Google News — her iki takım
        home_news, home_err = fetch_team_news(home)
        away_news, away_err = fetch_team_news(away)

        all_news = home_news + away_news
        news_conf = 0.1
        if len(all_news) >= 5:
            news_conf = 0.4
        if len(all_news) >= 10:
            news_conf = 0.6

        # Basit injury / tempo keyword taraması (çok kaba ama gerçek haber üzerinden)
        inj_home = 0.0
        inj_away = 0.0
        pace_hint = "NEUTRAL"

        txt_all = " ".join(all_news).lower()

        injury_words = ["injury", "out", "doubtful", "questionable", "sakat", "sakatlık"]
        fast_words = ["fast pace", "high scoring", "offense", "run and gun", "hızlı hücum"]
        slow_words = ["defense", "low scoring", "savunma", "sert savunma"]

        for w in injury_words:
            if w in norm_name(" ".join(home_news)):
                inj_home += 0.3
            if w in norm_name(" ".join(away_news)):
                inj_away += 0.3

        fast_hit = any(w in txt_all for w in fast_words)
        slow_hit = any(w in txt_all for w in slow_words)
        if fast_hit and not slow_hit:
            pace_hint = "HIGH"
        elif slow_hit and not fast_hit:
            pace_hint = "LOW"

        # 4) Soft skor bandı
        low = main_total - 8.0
        mid = main_total
        high = main_total + 8.0

        over_bias = False
        under_bias = False

        if book_total is not None:
            if main_total - baseline >= 5.0:
                over_bias = True
            elif main_total - baseline <= -5.0:
                under_bias = True

        # FAZ-13 NewsSummary formatında cevap
        payload = {
            "league": league,
            "date": date,
            "home_team": home,
            "away_team": away,
            "total_view": {
                "consensus": consensus,
                "book_main_total": float(main_total),
                "avg_line": float(main_total),
                "notes": barem_meta,
            },
            "tempo": {
                "pace_hint": pace_hint,
                "attack_focus": None,
                "defense_focus": None,
            },
            "injuries": {
                "home": float(round(inj_home, 2)),
                "away": float(round(inj_away, 2)),
            },
            "fatigue": {
                "home": 0.0,
                "away": 0.0,
                "diff": 0.0,
            },
            "spread_view": {
                "fav_team": None,
                "fav_spread": None,
                "comment": None,
            },
            "soft_score_range": {
                "low": float(round(low, 1)),
                "mid": float(round(mid, 1)),
                "high": float(round(high, 1)),
            },
            "flags": {
                "over_bias": over_bias,
                "under_bias": under_bias,
                "trap_like": False,
            },
            "confidence": {
                "news_confidence": float(round(news_conf, 2)),
                "book_confidence": 0.7 if book_total is not None else 0.4,
                "overall": float(round(0.5 + (news_conf - 0.3), 2)),
            },
            "key_quotes": all_news[:10],
            "sources_used": [
                s
                for s in [
                    "mackolik_program" if book_total is not None else None,
                    "google_news",
                ]
                if s
            ],
        }

        return JSONResponse(payload)

    except Exception as e:
        return JSONResponse(
            {
                "error": str(e),
                "trace": traceback.format_exc(),
                "fallback": True,
            },
            status_code=500,
        )


# ------------------------------------------------------------
# ✔ HEALTH / PING
# ------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "uptime": time.time()}


@app.get("/ping")
def ping():
    return {"status": "ok", "uptime": time.time()}


# ------------------------------------------------------------
# MAIN (Fly.io uvicorn runner)
# ------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        workers=1,
    )
