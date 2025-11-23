import time
from dataclasses import dataclass, asdict
from typing import Dict, Any, Literal, Optional

InputSource = Literal["api", "manual", "visual"]


@dataclass
class FusionInput:
    """
    FAZ-13 unified input format.

    Her kaynaktan (API / manual / görsel) gelen veriyi
    aynı şemaya sokuyoruz ki FAZ-10 → FAZ-11 → FAZ-12
    pipeline'ına tek tip obje gitsin.
    """
    source: InputSource          # "api" | "manual" | "visual"
    league: str                  # "NBA", "EL", vs.
    home: str
    away: str
    market: str                  # "total_points", "home_total", ...
    line: float                  # 220.5 gibi
    side: str                    # "OVER" / "UNDER" / "UNKNOWN"
    odds: float                  # bookmaker oranı
    ts: float                    # timestamp
    raw: Dict[str, Any]          # ham veri (debug / log için)


# -----------------------------------------------------------
# 📝 MANUAL INPUT (Telegram text)
# -----------------------------------------------------------

def normalize_manual_text(text: str, default_league: str = "NBA") -> FusionInput:
    """
    Beklenen format (önerilen):

        /mac BOS ORL 220.5 U 1.46

    veya

        BOS ORL 220.5 U 1.46

    Sıra:
        1) Home team (kısa kod da olur)
        2) Away team
        3) Line (float, virgül veya nokta)
        4) Yön  ->  U / ALT / UNDER  ya da  O / ÜST / OVER
        5) Oran ->  1.46 gibi
    """
    text = text.strip()
    parts = text.split()

    # /mac @bot falan yazıldıysa komut kısmını at
    if parts and parts[0].startswith("/"):
        # örn: "/mac", "/mac@zeynalbot"
        parts = parts[1:]

    if not parts or len(parts) < 5:
        raise ValueError(
            "Manual input formatı hatalı. Örnek: 'BOS ORL 220.5 U 1.46'"
        )

    home = parts[0]
    away = parts[1]

    # line
    try:
        line = float(parts[2].replace(",", "."))
    except Exception:
        raise ValueError(f"Line sayısı okunamadı: {parts[2]!r}")

    # side
    side_token = parts[3].upper()
    if side_token in ("A", "ALT", "U", "UNDER"):
        side = "UNDER"
    elif side_token in ("Ü", "UST", "ÜST", "O", "OVER"):
        side = "OVER"
    else:
        side = "UNKNOWN"

    # odds
    try:
        odds = float(parts[4].replace(",", "."))
    except Exception:
        raise ValueError(f"Oran okunamadı: {parts[4]!r}")

    return FusionInput(
        source="manual",
        league=default_league,
        home=home,
        away=away,
        market="total_points",
        line=line,
        side=side,
        odds=odds,
        ts=time.time(),
        raw={"tokens": parts},
    )


# -----------------------------------------------------------
# 🌐 API INPUT (otomatik veri)
# -----------------------------------------------------------

def normalize_api_data(data: Dict[str, Any]) -> FusionInput:
    """
    API'den gelen JSON'u tek forma çevirir.
    Burada data şemasını sen belirleyeceksin.
    Örnek beklenen key'ler:

        {
          "league": "NBA",
          "home": "BOS",
          "away": "ORL",
          "market": "total_points",
          "line": 220.5,
          "side": "OVER",
          "odds": 1.46
        }
    """
    league = str(data.get("league", "NBA"))
    home = str(data.get("home", "HOME"))
    away = str(data.get("away", "AWAY"))
    market = str(data.get("market", "total_points"))

    line = float(str(data.get("line", "0")).replace(",", "."))
    odds = float(str(data.get("odds", "1.0")).replace(",", "."))

    side_raw = str(data.get("side", "")).upper()
    if side_raw in ("A", "ALT", "U", "UNDER"):
        side = "UNDER"
    elif side_raw in ("Ü", "UST", "ÜST", "O", "OVER"):
        side = "OVER"
    else:
        side = "UNKNOWN"

    return FusionInput(
        source="api",
        league=league,
        home=home,
        away=away,
        market=market,
        line=line,
        side=side,
        odds=odds,
        ts=time.time(),
        raw=data,
    )


# -----------------------------------------------------------
# 📸 VISUAL INPUT (ekran görüntüsü)
# -----------------------------------------------------------

def normalize_visual_meta(meta: Dict[str, Any]) -> FusionInput:
    """
    Görselden okuduğun veriyi (ister elle, ister OCR ile)
    tek forma çeviriyorsun.

    Örnek meta:

        {
          "league": "NBA",
          "home": "BOS",
          "away": "ORL",
          "market": "total_points",
          "line": 220.5,
          "side": "OVER",
          "odds": 1.46,
          "screenshot_id": "...",
        }

    Şimdilik OCR yok, sen görseli atıp yanında bu bilgileri
    text olarak da geçebilirsin. Sonra OCR eklenebilir.
    """
    league = str(meta.get("league", "NBA"))
    home = str(meta.get("home", "HOME"))
    away = str(meta.get("away", "AWAY"))
    market = str(meta.get("market", "total_points"))

    line = float(str(meta.get("line", "0")).replace(",", "."))
    odds = float(str(meta.get("odds", "1.0")).replace(",", "."))

    side_raw = str(meta.get("side", "")).upper()
    if side_raw in ("A", "ALT", "U", "UNDER"):
        side = "UNDER"
    elif side_raw in ("Ü", "UST", "ÜST", "O", "OVER"):
        side = "OVER"
    else:
        side = "UNKNOWN"

    return FusionInput(
        source="visual",
        league=league,
        home=home,
        away=away,
        market=market,
        line=line,
        side=side,
        odds=odds,
        ts=time.time(),
        raw=meta,
    )
