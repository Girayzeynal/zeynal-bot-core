import re
from dataclasses import dataclass
from typing import Optional, Dict, Any


# =====================================================================
# 🔧 SAFE FLOAT
# =====================================================================
def _safe_float(val) -> Optional[float]:
    """Herhangi bir string'i güvenli şekilde floata çevirir."""
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "."))
    except Exception:
        return None


# =====================================================================
# 🧱 Ortak Meta Model (hafif versiyon)
# =====================================================================
@dataclass
class MatchMeta:
    source: str
    raw: str
    league: str = "NBA"
    home: str = "UNKNOWN"
    away: str = "UNKNOWN"
    market: str = "FT TOTAL"
    line: Optional[float] = None
    direction: Optional[str] = None  # "U" / "O"
    odds: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "raw": self.raw,
            "league": self.league,
            "home": self.home,
            "away": self.away,
            "market": self.market,
            "line": self.line,
            "direction": self.direction,
            "odds": self.odds,
        }


# =====================================================================
# 🧠 FAZ-13.2 — HYBRID PRECISION MANUAL PARSER
# =====================================================================
def normalize_manual_text(text: str, default_league: str = "NBA") -> Dict[str, Any]:
    """
    FAZ-13.2 manuel parser — tüm ters formatlar, hatalı girişler,
    virgül/nokta, takım sırası, line/odds/direction yakalama.
    GOD-LAYER için optimize edilmiştir.

    Örnekler:
      /mac BOS ORL 220.5 U 1.46
      /mac BOS ORL U 220.5 1.46
      /mac FENER EFES 167,5 U
      BOS ORL 220.5 U
    """
    raw_text = (text or "").strip()

    # Prefix temizliği (/mac, /live vs)
    if raw_text.startswith("/"):
        parts = raw_text.split(maxsplit=1)
        args = parts[1] if len(parts) > 1 else ""
    else:
        args = raw_text

    # Token cleanup
    args = args.replace("\n", " ").replace("\t", " ")
    raw_tokens = [t for t in args.split(" ") if t.strip()]

    tokens = []
    for t in raw_tokens:
        f = _safe_float(t)
        if f is not None:
            tokens.append(str(f))          # normalize numeric
        else:
            tokens.append(t.upper())       # normalize string

    # Hiç token yoksa minimum çıktı
    if not tokens:
        return MatchMeta(
            source="manual",
            raw=raw_text,
            league=default_league,
        ).to_dict()

    # League detect
    league_tags = {"NBA", "EUROLEAGUE", "EL", "BSL", "TBL"}
    league = default_league
    cleaned = []
    for t in tokens:
        if t in league_tags:
            league = t
        else:
            cleaned.append(t)
    tokens = cleaned

    # Float index (line/odds)
    float_idx = [i for i, t in enumerate(tokens) if _safe_float(t) is not None]

    line = None
    odds = None
    direction = None

    def _norm_dir(tok: Optional[str]) -> Optional[str]:
        if tok is None:
            return None
        tok = tok.upper()
        if tok in ("U", "UNDER", "ALT"):
            return "U"
        if tok in ("O", "OVER", "ÜST", "UST"):
            return "O"
        return None

    # Line / Odds / Direction
    if float_idx:
        if len(float_idx) >= 2:
            line_pos = float_idx[-2]
            odds_pos = float_idx[-1]
            line = _safe_float(tokens[line_pos])
            odds = _safe_float(tokens[odds_pos])
        else:
            line_pos = float_idx[0]
            line = _safe_float(tokens[line_pos])

        # Direction sağ taraf
        if line_pos + 1 < len(tokens):
            direction = _norm_dir(tokens[line_pos + 1])

        # Direction sol taraf
        if direction is None and line_pos - 1 >= 0:
            direction = _norm_dir(tokens[line_pos - 1])

        first_num_idx = float_idx[0]
    else:
        first_num_idx = len(tokens)

    # Team parse
    team_tokens = tokens[:first_num_idx]

    if len(team_tokens) >= 2:
        mid = len(team_tokens) // 2
        home = " ".join(team_tokens[:mid])
        away = " ".join(team_tokens[mid:])
    elif len(team_tokens) == 1:
        home = team_tokens[0]
        away = "UNKNOWN"
    else:
        home = "UNKNOWN"
        away = "UNKNOWN"

    meta = MatchMeta(
        source="manual",
        raw=raw_text,
        league=league,
        home=home,
        away=away,
        market="FT TOTAL",
        line=line,
        direction=direction,
        odds=odds,
    )
    return meta.to_dict()


# =====================================================================
# 📸 VISUAL META NORMALIZER
# =====================================================================
def normalize_visual_meta(ocr_text: str, default_league: str = "NBA") -> Dict[str, Any]:
    """
    Visual OCR metnini FAZ-13 meta formatına çevirir.
    Basit ama kararlı heuristik versiyon.
    """
    if not ocr_text:
        return MatchMeta(
            source="visual",
            raw="",
            league=default_league,
        ).to_dict()

    text = ocr_text.upper().replace("\n", " ")

    # HOME / AWAY tahmini (çok basit heuristik)
    words = text.split()
    if len(words) >= 2:
        home = words[0]
        away = words[1]
    else:
        home = "TEAM1"
        away = "TEAM2"

    # Line yakalama (örn: 220.5 / 167.5)
    regex = r"(\d{2,3}[.,]?\d*)"
    found_nums = re.findall(regex, text)
    line = None
    if found_nums:
        line = _safe_float(found_nums[-1])

    # U/O detect
    if "UNDER" in text or "ALT" in text or " U " in text:
        direction = "U"
    elif "OVER" in text or "UST" in text or " O " in text:
        direction = "O"
    else:
        direction = None

    meta = MatchMeta(
        source="visual",
        raw=ocr_text,
        league=default_league,
        home=home,
        away=away,
        market="FT TOTAL",
        line=line,
        direction=direction,
        odds=None,
    )
    return meta.to_dict()


# =====================================================================
# 🌐 API DATA NORMALIZER
# =====================================================================
def normalize_api_data(api_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    API'den gelen live/prematch verisini FAZ-13 meta formatına çevirir.

    Beklenen minimal input örneği:
      {
        "league": "NBA",
        "home_name": "BOS",
        "away_name": "ORL",
        "market": "FT TOTAL",
        "line": 220.5,
        "direction": "U",
        "odds": 1.46
      }
    """
    data = api_payload or {}

    league = (data.get("league") or "NBA").upper()
    home = data.get("home_name") or data.get("home") or "UNKNOWN"
    away = data.get("away_name") or data.get("away") or "UNKNOWN"
    market = data.get("market") or "FT TOTAL"
    line = data.get("line")
    direction = data.get("direction")
    odds = data.get("odds")

    line_val = _safe_float(line)

    if isinstance(direction, str):
        d = direction.upper()
        if d in ("U", "UNDER", "ALT"):
            direction_norm = "U"
        elif d in ("O", "OVER", "ÜST", "UST"):
            direction_norm = "O"
        else:
            direction_norm = None
    else:
        direction_norm = None

    meta = MatchMeta(
        source="api",
        raw=str(api_payload),
        league=league,
        home=home,
        away=away,
        market=market,
        line=line_val,
        direction=direction_norm,
        odds=odds,
    )
    return meta.to_dict()
