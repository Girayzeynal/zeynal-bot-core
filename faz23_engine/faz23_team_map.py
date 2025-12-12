# -*- coding: utf-8 -*-
"""
FAZ-23 Team Map
- Dış API'lerde takım isimleri bazen farklı yazılır (Bucks vs Milwaukee Bucks gibi).
- map_team() ile "kanonik" isim döndürürüz.
"""

from __future__ import annotations
import re
from typing import Dict


def normalize_team_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^\w\s\-\.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# NBA ağırlıklı alias seti (gerek oldukça genişletirsin)
ALIASES: Dict[str, str] = {
    # Milwaukee
    "milwaukee": "Milwaukee Bucks",
    "milwaukee bucks": "Milwaukee Bucks",
    "bucks": "Milwaukee Bucks",

    # Boston
    "boston": "Boston Celtics",
    "boston celtics": "Boston Celtics",
    "celtics": "Boston Celtics",

    # Lakers / Bulls örnek
    "la lakers": "Los Angeles Lakers",
    "los angeles lakers": "Los Angeles Lakers",
    "lakers": "Los Angeles Lakers",

    "chicago": "Chicago Bulls",
    "chicago bulls": "Chicago Bulls",
    "bulls": "Chicago Bulls",
}


def map_team(name: str) -> str:
    """
    Dış API ismini -> kanonik takım ismine mapler.
    Bulamazsa input'u Title Case gibi döndürür.
    """
    norm = normalize_team_name(name)
    if not norm:
        return ""

    if norm in ALIASES:
        return ALIASES[norm]

    # "Milwaukee (Bucks)" gibi şeyleri sadeleştir
    norm2 = re.sub(r"\(.*?\)", "", norm).strip()
    if norm2 in ALIASES:
        return ALIASES[norm2]

    # Fallback
    return " ".join([w.capitalize() for w in norm2.split()])
