# faz13_engine/league_autodetect.py
# ============================================
# FAZ-GLOBAL LEAGUE AUTO-DETECT
# Takım adından lig tahmini yapan basit katman.
# Haritayı zamanla genişleteceğiz.

from typing import Optional, List
import unicodedata


def _norm(text: str) -> str:
    """
    Basit normalize:
    - Küçük harfe çevir
    - Türkçe karakterleri düzleştir (ş -> s, ç -> c vs.)
    - Fazla boşlukları temizle
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().strip().split())


# İlk global harita (örnekler)
TEAM_LEAGUE_MAP = {
    # EuroLeague
    "crvena zvezda": "Euroleague",
    "kizilyildiz": "Euroleague",
    "crvena zvezda mts": "Euroleague",
    "barcelona": "Euroleague",
    "fc barcelona": "Euroleague",

    # Türkiye BSL / TBSL
    "tupras buyukcekmece": "TBSL",
    "buyukcekmece": "TBSL",
    "mersin spor": "TBSL",
    "mersin buyuksehir": "TBSL",

    # Buraya zamanla NBA, diğer ligler vs. eklenecek
}


def guess_league(
    home_team: str,
    away_team: str,
    hint_league: Optional[str] = None,
) -> (str, List[str]):
    """
    Lig tahmini yapar.

    - hint_league dolu ve AUTO / ? değilse -> direkt onu kullanır.
    - Haritada hem ev hem deplasman için aynı lig bulunursa → onu seçer.
    - Sadece bir taraf bulunursa → onu seçer.
    - Hiç bulunamazsa → "GLOBAL" döner.
    """

    notes: List[str] = []

    # Kullanıcı lig yazmışsa ve bu 'AUTO' / '?' değilse: dokunma.
    if hint_league and hint_league.strip() and hint_league.strip().upper() not in {"AUTO", "?", "GLOBAL"}:
        notes.append(f"Lig kullanıcı tarafından verildi: {hint_league}")
        return hint_league.strip(), notes

    h = _norm(home_team)
    a = _norm(away_team)

    lg_home = TEAM_LEAGUE_MAP.get(h)
    lg_away = TEAM_LEAGUE_MAP.get(a)

    if lg_home and lg_away and lg_home == lg_away:
        notes.append(f"Her iki takım da {lg_home} haritasında bulundu.")
        return lg_home, notes

    if lg_home:
        notes.append(f"Ev sahibi takım {lg_home} haritasında bulundu.")
        return lg_home, notes

    if lg_away:
        notes.append(f"Deplasman takım {lg_away} haritasında bulundu.")
        return lg_away, notes

    notes.append("Lig haritada bulunamadı → GLOBAL etiketi ile devam.")
    return "GLOBAL", notes
