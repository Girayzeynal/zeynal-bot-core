from __future__ import annotations

# -*- coding: utf-8 -*-
"""
FAZ-23 Team Map (FINAL BUILD)

Amaç:
- Dış API'lerden gelen takım isimlerini kanonik forma normalize etmek
- API-Sports / Odds / balldontlie farklarını absorbe etmek
- FAZ-23 DataHub & Meta Engine için stabil takım eşlemesi sağlamak
"""

import re
from typing import Dict


# ------------------------------------------------------------
# Normalization helpers
# ------------------------------------------------------------

def normalize_team_name(name: str) -> str:
    """
    Takım adını normalize eder:
    - lower
    - özel karakterleri temizler
    - fazla boşlukları sadeleştirir
    """
    s = (name or "").strip().lower()
    s = re.sub(r"[^\w\s\-\.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ------------------------------------------------------------
# Alias map (NBA ağırlıklı, genişletilebilir)
# ------------------------------------------------------------

ALIASES: Dict[str, str] = {
    # Milwaukee
    "milwaukee": "Milwaukee Bucks",
    "milwaukee bucks": "Milwaukee Bucks",
    "bucks": "Milwaukee Bucks",

    # Boston
    "boston": "Boston Celtics",
    "boston celtics": "Boston Celtics",
    "celtics": "Boston Celtics",

    # Lakers
    "la lakers": "Los Angeles Lakers",
    "los angeles lakers": "Los Angeles Lakers",
    "lakers": "Los Angeles Lakers",

    # Bulls
    "chicago": "Chicago Bulls",
    "chicago bulls": "Chicago Bulls",
    "bulls": "Chicago Bulls",
}


# ------------------------------------------------------------
# Public API
# ------------------------------------------------------------

def map_team(name: str) -> str:
    """
    Dış API takım adını → kanonik FAZ-23 takım adına mapler.
    Bulamazsa Title Case fallback döner.
    """
    norm = normalize_team_name(name)
    if not norm:
        return ""

    # Direkt alias
    if norm in ALIASES:
        return ALIASES[norm]

    # Parantez temizleme (örn: "Milwaukee (Bucks)")
    norm2 = re.sub(r"\(.*?\)", "", norm).strip()
    if norm2 in ALIASES:
        return ALIASES[norm2]

    # Fallback → Title Case
    return " ".join(w.capitalize() for w in norm2.split())


# ------------------------------------------------------------
# Runtime anchor (Fly.io / Docker image guarantee)
# ------------------------------------------------------------

def _faz23_team_map_runtime_anchor() -> bool:
    """
    Fly.io runtime anchor.
    Bu fonksiyon çağrıldığında dosyanın image içine
    kesin olarak alınmasını garanti eder.
    """
    return True
