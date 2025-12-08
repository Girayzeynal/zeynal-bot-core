"""
FAZ-13 NEWS SCRAPER ENGINE
==========================

Bu dosya, FAZ-13 / FAZ-17 / FAZ-22 / FAZ-23 çekirdeklerine
"HABER + EDITÖR YORUMU + SAKATLIK + BAREM TRENDİ" bilgisini veren
merkezi motorun TEK BLOK iskeletini içerir.
"""

from __future__ import annotations
import json
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
import re

log = logging.getLogger(__name__)

# =====================================================================
# 🔥 0) GLOBAL SLUG FIX — (tuple/list/None/sayı crash fix)
# =====================================================================
def slug(x):
    """
    Evrensel güvenli slug dönüştürücü.
    Her türlü input'u (tuple, list, None, int, float) güvenli stringe çevirir.
    """
    if x is None:
        return "NONE"

    if isinstance(x, tuple):
        x = " ".join(str(i) for i in x)

    if isinstance(x, list):
        x = " ".join(str(i) for i in x)

    x = str(x)

    return re.sub(r"[^A-Za-z0-9]+", "_", x).strip("_").upper()


# =====================================================================
# 0) CONFIG & REGISTRY
# =====================================================================

NEWS_CACHE_PATH = "/data/faz13/faz13_news_cache.jsonl"

SOURCE_REGISTRY = {
    "injuries": [
        "espn_nba_injuries",
        "cbs_nba_injuries",
        "fox_nba_injuries",
        "rotowire_lineups",
    ],
    "tempo": [
        "basketball_reference",
        "nba_advanced_stats",
        "teamrankings_pace",
        "euroleague_stats",
    ],
    "news": [
        "yahoo_nba_news",
        "bleacher_report",
        "the_athletic",
        "hoopshype",
        "eurohoops",
        "basketnews",
        "aa_sports_tr",
        "club_official_news",
    ],
    "odds": [
        "oddsportal",
        "flashscore",
    ],
    "local_tr": [
        "basketfaul",
        "tbf_news",
    ],
}

# =====================================================================
# 1) DATA MODELS
# =====================================================================

@dataclass
class MatchMeta:
    league: str
    date: str
    home_team: str
    away_team: str

    @property
    def match_key(self) -> str:
        """
        Global crash-safe slug sistemi ile match_key üret.
        """
        return f"{slug(self.league)}|{self.date}|{slug(self.home_team)}|{slug(self.away_team)}"


@dataclass
class RawNewsPacket:
    source: str
    lang: str
    url: str
    fetched_at: float
    raw_text: str
    meta: Dict
    trust_score: float


@dataclass
class MatchNewsSummary:
    match_key: str
    home_team: str
    away_team: str

    injuries: Dict = field(default_factory=dict)
    fatigue: Dict = field(default_factory=dict)
    tempo: Dict = field(default_factory=dict)
    spread_view: Dict = field(default_factory=dict)
    total_view: Dict = field(default_factory=dict)
    soft_score_range: Dict = field(default_factory=dict)

    flags: List[str] = field(default_factory=list)
    confidence: float = 0.0

    key_quotes: List[str] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)


# =====================================================================
# 2) CACHE YAPISI
# =====================================================================

def _ensure_cache_file():
    try:
        open(NEWS_CACHE_PATH, "a", encoding="utf-8").close()
    except Exception as e:
        log.warning("NEWS_CACHE_PATH yaratılırken hata: %s", e)


def load_from_cache(match_key: str) -> Optional[MatchNewsSummary]:
    _ensure_cache_file()
    now = time.time()
    max_age = 6 * 3600  # 6 saat

    try:
        with open(NEWS_CACHE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("match_key") != match_key:
                    continue

                if now - obj.get("fetched_at", 0) > max_age:
                    return None

                summary_dict = obj.get("summary")
                if not summary_dict:
                    return None

                return MatchNewsSummary(**summary_dict)

    except FileNotFoundError:
        return None
    except Exception as e:
        log.warning("News cache okunamadı: %s", e)
        return None

    return None


def save_to_cache(summary: MatchNewsSummary):
    _ensure_cache_file()
    try:
        with open(NEWS_CACHE_PATH, "a", encoding="utf-8") as f:
            record = {
                "match_key": summary.match_key,
                "fetched_at": time.time(),
                "summary": asdict(summary),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning("News cache yazılamadı: %s", e)


# =====================================================================
# 3) SOURCE ADAPTER İSKELETLERİ
# =====================================================================

def fetch_from_euroleague_game_center(match_meta: MatchMeta) -> List[RawNewsPacket]:
    return []

def fetch_from_eurohoops(match_meta: MatchMeta) -> List[RawNewsPacket]:
    return []

def fetch_from_basketnews(match_meta: MatchMeta) -> List[RawNewsPacket]:
    return []

def fetch_from_aa_sports(match_meta: MatchMeta) -> List[RawNewsPacket]:
    return []

def fetch_from_oddsportal(match_meta: MatchMeta) -> List[RawNewsPacket]:
    return []

def fetch_from_flashscore(match_meta: MatchMeta) -> List[RawNewsPacket]:
    return []

def fetch_from_club_official(match_meta: MatchMeta) -> List[RawNewsPacket]:
    return []


def fetch_raw_packets(match_meta: MatchMeta) -> List[RawNewsPacket]:
    adapters = [
        fetch_from_euroleague_game_center,
        fetch_from_eurohoops,
        fetch_from_basketnews,
        fetch_from_aa_sports,
        fetch_from_oddsportal,
        fetch_from_flashscore,
        fetch_from_club_official,
    ]

    packets = []
    for adapter in adapters:
        try:
            sub = adapter(match_meta)
            if sub:
                packets.extend(sub)
        except Exception as e:
            log.warning("News adapter %s hata verdi: %s", adapter.__name__, e)
    return packets


# =====================================================================
# 4) NORMALIZER
# =====================================================================

def _extract_injury_info(packets, match_meta):
    home_out = set()
    away_out = set()

    patterns_tr = [
        r"(.+?)\s+oynamayacak",
        r"(.+?)\s+forma giymeyecek",
        r"(.+?)\s+yer almayacak",
    ]
    patterns_en = [
        r"(.+?)\s+out\b",
        r"(.+?)\s+won't play",
        r"(.+?)\s+ruled out",
    ]

    for pkt in packets:
        text = pkt.raw_text.lower()
        for pat in patterns_tr + patterns_en:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                name = m.group(1).strip()
                if not name:
                    continue
                if match_meta.home_team.lower().split()[0] in text:
                    home_out.add(name)
                elif match_meta.away_team.lower().split()[0] in text:
                    away_out.add(name)

    return {
        "home_out": sorted(home_out),
        "away_out": sorted(away_out),
        "impact_home": min(1.0, 0.1 * len(home_out)),
        "impact_away": min(1.0, 0.1 * len(away_out)),
    }


def _extract_total_spread_view(packets):
    total_votes = {"OVER": 0.0, "UNDER": 0.0}
    spread_votes = {"HOME": 0.0, "AWAY": 0.0}
    total_ranges = []

    for pkt in packets:
        txt = pkt.raw_text.lower()
        w = pkt.trust_score or 0.5

        if "üst" in txt or "over" in txt:
            total_votes["OVER"] += w
        if "alt" in txt or "under" in txt:
            total_votes["UNDER"] += w

        for m in re.finditer(r"(\d{3}\.\d)", txt):
            try:
                total_ranges.append(float(m.group(1)))
            except:
                pass

        if "ev sahibi" in txt or "home team" in txt:
            spread_votes["HOME"] += w
        if "deplasman" in txt or "away team" in txt:
            spread_votes["AWAY"] += w

    def choose(v):
        if not v:
            return "NEUTRAL"
        return max(v, key=v.get)

    total_cons = choose(total_votes)
    spread_cons = choose(spread_votes)

    if total_ranges:
        avg_barem = sum(total_ranges) / len(total_ranges)
        key_range = [avg_barem - 4, avg_barem + 4]
    else:
        avg_barem = None
        key_range = []

    return (
        {
            "consensus": total_cons,
            "avg_line": avg_barem,
            "key_range": key_range,
            "votes": total_votes,
        },
        {
            "consensus": spread_cons,
            "votes": spread_votes,
        },
    )


def _estimate_soft_score_range(total_view, match_meta):
    center = (
        total_view["avg_line"]
        if total_view.get("avg_line")
        else 165.0
        if match_meta.league.lower() == "euroleague"
        else 220.0
    )
    return {"low": center - 8, "center": center, "high": center + 8}


def normalize_packets(packets, match_meta):
    summary = MatchNewsSummary(
        match_key=match_meta.match_key,
        home_team=match_meta.home_team,
        away_team=match_meta.away_team,
    )

    if not packets:
        summary.confidence = 0.0
        summary.flags.append("NO_NEWS_DATA")
        return summary

    summary.injuries = _extract_injury_info(packets, match_meta)
    total_view, spread_view = _extract_total_spread_view(packets)

    summary.total_view = total_view
    summary.spread_view = spread_view
    summary.soft_score_range = _estimate_soft_score_range(total_view, match_meta)

    tempo_flags = {"HIGH": 0, "LOW": 0, "MID": 0}
    evidence = []

    for pkt in packets:
        txt = pkt.raw_text.lower()
        w = pkt.trust_score or 0.5
        if any(k in txt for k in ["yüksek tempo", "high-paced", "fastbreak"]):
            tempo_flags["HIGH"] += w
        if any(k in txt for k in ["savunma maçı", "defensive battle"]):
            tempo_flags["LOW"] += w

    tempo_hint = max(tempo_flags, key=tempo_flags.get)
    summary.tempo = {"pace_hint": tempo_hint, "votes": tempo_flags, "evidence": evidence}

    flags = []
    base = 0.5

    if summary.injuries.get("impact_home") > 0.2:
        flags.append("INJURY_RELEVANT")
        base += 0.1

    if summary.total_view.get("consensus") in ("OVER", "UNDER"):
        flags.append(f"TOTAL_{summary.total_view['consensus']}")
        base += 0.1

    if summary.spread_view.get("consensus") in ("HOME", "AWAY"):
        flags.append(f"SPREAD_{summary.spread_view['consensus']}")
        base += 0.1

    if tempo_hint != "MID":
        flags.append(f"TEMPO_{tempo_hint}")
        base += 0.05

    summary.flags = flags
    summary.confidence = min(1.0, base)
    summary.sources_used = sorted({pkt.source for pkt in packets})

    return summary


# =====================================================================
# 5) FEATURE ENCODER
# =====================================================================

def encode_news_features(summary: MatchNewsSummary) -> Dict:
    injuries = summary.injuries or {}
    fatigue = summary.fatigue or {}
    tempo = summary.tempo or {}
    total_view = summary.total_view or {}
    spread_view = summary.spread_view or {}

    return {
        "news_inj_impact_home": float(injuries.get("impact_home", 0)),
        "news_inj_impact_away": float(injuries.get("impact_away", 0)),

        "news_fatigue_diff": float(fatigue.get("fatigue_diff", 0)),

        "news_pace_high_flag": 1.0 if tempo.get("pace_hint") == "HIGH" else 0.0,
        "news_pace_low_flag": 1.0 if tempo.get("pace_hint") == "LOW" else 0.0,

        "news_total_over_flag": 1.0 if total_view.get("consensus") == "OVER" else 0.0,
        "news_total_under_flag": 1.0 if total_view.get("consensus") == "UNDER" else 0.0,
        "news_total_avg_line": float(total_view.get("avg_line") or 0),

        "news_spread_home_flag": 1.0 if spread_view.get("consensus") == "HOME" else 0.0,
        "news_spread_away_flag": 1.0 if spread_view.get("consensus") == "AWAY" else 0.0,

        "news_confidence": float(summary.confidence),
        "news_flag_injury_relevant": 1.0 if "INJURY_RELEVANT" in summary.flags else 0.0,
    }


# =====================================================================
# 6) ANA GİRİŞ
# =====================================================================

def get_match_news(match_meta: MatchMeta, use_cache=True):
    if use_cache:
        cached = load_from_cache(match_meta.match_key)
        if cached:
            log.info("NewsScraper: cache'den okundu: %s", match_meta.match_key)
            return cached, encode_news_features(cached)

    packets = fetch_raw_packets(match_meta)
    summary = normalize_packets(packets, match_meta)

    if use_cache:
        save_to_cache(summary)

    feats = encode_news_features(summary)
    return summary, feats


# =====================================================================
# 7) TEST
# =====================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    meta = MatchMeta(
        league="Euroleague",
        date="2025-12-05",
        home_team="Crvena Zvezda",
        away_team="Barcelona",
    )
    s, f = get_match_news(meta, use_cache=False)
    print(json.dumps(asdict(s), indent=2, ensure_ascii=False))
    print(json.dumps(f, indent=2, ensure_ascii=False))
