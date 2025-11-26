import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

app = Flask(__name__)


def parse_match_page(url: str):
    """
    Mackolik maç sayfasını alıp JSON formatına dönüştürür.
    """
    try:
        html = requests.get(url, timeout=8).text
    except Exception:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Takım isimleri
    try:
        teams = soup.select(".teams h3")
        home_name = teams[0].text.strip().upper()
        away_name = teams[1].text.strip().upper()
    except:
        home_name = "HOME"
        away_name = "AWAY"

    # Skor
    try:
        scores = soup.select(".score span")
        home_score = int(scores[0].text.strip())
        away_score = int(scores[1].text.strip())
    except:
        home_score = 0
        away_score = 0

    # Periyot / Durum
    try:
        period = soup.select_one(".period").text.strip()
    except:
        period = "Q1"

    try:
        clock = soup.select_one(".clock").text.strip()
    except:
        clock = "00:00"

    win_side = "HOME" if home_score >= away_score else "AWAY"

    return {
        "league": "MACKOLIK",
        "match_id": url.split("/")[-1],
        "home_name": home_name,
        "away_name": away_name,
        "home_score": home_score,
        "away_score": away_score,
        "period": period,
        "clock": clock,
        "status": "LIVE",
        "win_side_label": win_side,
        "win_prob": 0.55 if win_side == "HOME" else 0.45,
        "provider": "MACKOLIK",
    }


@app.get("/live")
def get_live():
    """
    Örnek:
      /live?match_id=4406870
      /live?home=FENERBAHÇE&away=EFES
    """

    match_id = request.args.get("match_id")
    home = request.args.get("home")
    away = request.args.get("away")

    # 1) ID MODE
    if match_id:
        url = f"https://arsiv.mackolik.com/Basketball/Comparison/Default.aspx?id={match_id}"
        data = parse_match_page(url)
        return jsonify(data or {})

    # 2) TEAM MODE
    if home and away:
        # Buraya istersen gelecekte “arama” ekleriz
        return jsonify({})

    return jsonify({})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
