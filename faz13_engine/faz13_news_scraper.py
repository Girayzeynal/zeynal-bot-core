"""
FAZ-13 NEWS SCRAPER ENGINE
==========================

Bu dosya, FAZ-13 / FAZ-17 / FAZ-22 / FAZ-23 çekirdeklerine
"HABER + EDITÖR YORUMU + SAKATLIK + BAREM TRENDİ" bilgisini veren
merkezi motorun TEK BLOK iskeletini içerir.

HEDEF:
    - Link bazlı haber / preview / injury / odds sayfalarını çekmek
    - Hepsini ortak bir şemaya normalize etmek
    - FAZ-13 tahmin motoruna:
        * MatchNewsSummary (insan gibi özet)
        * news_features (sayısallaştırılmış sinyaller)
      olarak sunmak.

MİMARİ ÖZETİ:
    1) MatchMeta -> hangi maç için veri çekiyoruz?
    2) Source registry -> hangi siteler devrede? (ESPN, Euroleague, Basketnews, OddsPortal, vb.)
    3) fetch_raw_packets() -> her kaynaktan RawNewsPacket listesi
    4) normalize_packets() -> RawNewsPacket -> MatchNewsSummary
    5) encode_features() -> MatchNewsSummary -> news_features dict
    6) get_match_news() -> dış dünyaya dönen tek fonksiyon

NOT:
    - Buradaki HTTP ve HTML parse kısımları "örnek iskelet" şeklinde tutuldu.
      Gerçek projende:
        * requests + BeautifulSoup
        * veya httpx + selektörler
      kullanarak içerik dolduracaksın.
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
# 0) CONFIG & REGISTRY
# =====================================================================

# Bu path'i projende Fly.io volume'üne göre güncelle:
NEWS_CACHE_PATH = "/data/faz13/faz13_news_cache.jsonl"

# Kaynak kategorilerini senin daha önce belirlediğin yapıya göre kaydediyoruz.
# Burada isimler, ileride gerçek fetch fonksiyonlarına bağlanacak.
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
    """
    Bu maç için kimlik bilgisi.
    Örnek:
        league: "Euroleague"
        date: "2025-12-04"
        home_team: "Anadolu Efes"
        away_team: "Real Madrid"
    """
    league: str
    date: str
    home_team: str
    away_team: str

    @property
    def match_key(self) -> str:
        # Lig + tarih + takım isimlerini sadeleştirilmiş key'e çevir
        def slug(x: str) -> str:
            return re.sub(r"[^A-Za-z0-9]+", "_", x).strip("_").upper()

        return f"{slug(self.league)}|{self.date}|{slug(self.home_team)}|{slug(self.away_team)}"


@dataclass
class RawNewsPacket:
    """
    Her bir kaynaktan gelen ham metin ve meta bilgisi.
    Örnek: tek bir AA haberi, tek bir Basketnews preview yazısı, vb.
    """
    source: str           # "eurohoops", "basketnews", "oddsportal", vs.
    lang: str             # "tr", "en"
    url: str
    fetched_at: float
    raw_text: str         # HTML'den arındırılmış plain text
    meta: Dict            # Kaynağa özel ek bilgiler (önerilen bahis, barem vs.)
    trust_score: float    # 0.0 - 1.0 arası; kaynağın güvenilirliği


@dataclass
class MatchNewsSummary:
    """
    Bütün RawNewsPacket'lerin tek potada eritilip özetlendiği yapı.
    FAZ-13 / 17 / 22 / 23 buna bakarak 'insani' sinyal alır.
    """
    match_key: str
    home_team: str
    away_team: str

    # 1) SAKATLIK / KADRO
    injuries: Dict = field(default_factory=dict)  # {"home_out": [...], "away_out": [...], "impact_home": 0.2, ...}

    # 2) YORGUNLUK / TEMPO
    fatigue: Dict = field(default_factory=dict)   # {"home_b2b": False, "away_b2b": True, "fatigue_diff": +0.3}
    tempo: Dict = field(default_factory=dict)     # {"pace_hint": "HIGH"|"LOW"|"MID", "evidence": [...]}

    # 3) UZMAN GÖRÜŞLERİ (SPREAD / TOTAL)
    spread_view: Dict = field(default_factory=dict)  # {"consensus": "HOME"|"AWAY"|"NEUTRAL", "avg_line": -6.5, ...}
    total_view: Dict = field(default_factory=dict)   # {"consensus": "OVER"|"UNDER"|"NEUTRAL", "key_range": [226.5, 233.5]}

    # 4) SKOR ARALIĞI
    soft_score_range: Dict = field(default_factory=dict)  # {"low": 218, "center": 225, "high": 232}

    # 5) BAYRAKLAR & GÜVEN
    flags: List[str] = field(default_factory=list)  # ["HOME_FAV_STRONG", "AWAY_TIRED", "PACE_HIGH", ...]
    confidence: float = 0.0                         # 0.0 - 1.0 arası genel güven

    # 6) ÖNEMLİ CÜMLELER
    key_quotes: List[str] = field(default_factory=list)

    # 7) KULLANILAN KAYNAKLAR
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
    """
    JSONL cache içinden match_key'e uyan ilk kaydı bulmaya çalışır.
    Çok eski değilse (ör: 6 saat) direkt bunu dönebilirsin.
    """
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
                    # Çok eski, kullanma
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

# NOT: Bu fonksiyonlar şu an iskelet.
# Gerçek projende, her birini requests/httpx + BeautifulSoup ile dolduracaksın.
# Ama interface sabit kalacak: (match_meta: MatchMeta) -> List[RawNewsPacket]


def fetch_from_euroleague_game_center(match_meta: MatchMeta) -> List[RawNewsPacket]:
    """
    Örnek: EuroLeague resmi maç sayfası (game-center).
    - Kadro
    - Maç önü açıklamalar
    - H2H kısmi bilgi
    """
    # TODO: HTTP GET + parse işlemleri burada yapılacak.
    # Şimdilik boş döndürüyoruz.
    return []


def fetch_from_eurohoops(match_meta: MatchMeta) -> List[RawNewsPacket]:
    """
    Eurohoops'tan gelen haber / analizleri RawNewsPacket'e çevir.
    """
    return []


def fetch_from_basketnews(match_meta: MatchMeta) -> List[RawNewsPacket]:
    return []


def fetch_from_aa_sports(match_meta: MatchMeta) -> List[RawNewsPacket]:
    """
    Örnek: Anadolu Ajansı spor haberi.
    """
    return []


def fetch_from_oddsportal(match_meta: MatchMeta) -> List[RawNewsPacket]:
    """
    OddsPortal'dan:
      - açılış total baremi
      - güncel total baremi
      - açılış handikap
      - güncel handikap
    gibi veriler çekilip meta'da tutulur.
    """
    return []


def fetch_from_flashscore(match_meta: MatchMeta) -> List[RawNewsPacket]:
    """
    FlashScore maç sayfasından:
      - form
      - H2H
      - son maçlar
      vb. metin / yorum çekilebilir.
    """
    return []


def fetch_from_club_official(match_meta: MatchMeta) -> List[RawNewsPacket]:
    """
    Anadolu Efes SK, Real Madrid Basket gibi kulüp resmi sayfalarından:
      - maç önü haber
      - sakatlık açıklaması
      - koç yorumu
    """
    return []


# Buraya ihtiyaç oldukça ek adapter tanımlayabilirsin.
# Önemli olan hepsinin RawNewsPacket listesi döndürmesi.


def fetch_raw_packets(match_meta: MatchMeta) -> List[RawNewsPacket]:
    """
    Tüm kaynak adapter'lerini çağır, çıkan raw paketleri birleştir.
    """
    packets: List[RawNewsPacket] = []

    adapters = [
        fetch_from_euroleague_game_center,
        fetch_from_eurohoops,
        fetch_from_basketnews,
        fetch_from_aa_sports,
        fetch_from_oddsportal,
        fetch_from_flashscore,
        fetch_from_club_official,
        # ileride: ESPN, BasketballReference, Yahoo, vb. için benzer fonksiyonlar
    ]

    for adapter in adapters:
        try:
            sub = adapter(match_meta)
            if sub:
                packets.extend(sub)
        except Exception as e:
            log.warning("News adapter %s hata verdi: %s", adapter.__name__, e)

    return packets


# =====================================================================
# 4) NORMALIZER: RAW -> SUMMARY
# =====================================================================

def _extract_injury_info(packets: List[RawNewsPacket], match_meta: MatchMeta) -> Dict:
    """
    Metin içinden 'oynamayacak / sakat / questionable' gibi sinyalleri yakala.
    Bu basit bir örnek; sen bunu ileride oyuncu bazlı rating ile güçlendirebilirsin.
    """
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
        for pat in (patterns_tr + patterns_en):
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                name = m.group(1).strip()
                if not name:
                    continue
                # Çok basit ayrım: home/away içinde isim geçiyorsa ona yaz
                if match_meta.home_team.lower().split()[0] in text:
                    home_out.add(name)
                elif match_meta.away_team.lower().split()[0] in text:
                    away_out.add(name)

    # Şimdilik impact hesaplaması basit: oyuncu sayısına göre kabaca skor
    impact_home = min(1.0, 0.1 * len(home_out))
    impact_away = min(1.0, 0.1 * len(away_out))

    return {
        "home_out": sorted(home_out),
        "away_out": sorted(away_out),
        "impact_home": impact_home,
        "impact_away": impact_away,
    }


def _extract_total_spread_view(packets: List[RawNewsPacket]) -> Tuple[Dict, Dict]:
    """
    Haber / preview / odds kaynaklarından:
      - total_view (OVER / UNDER / NEUTRAL)
      - spread_view (HOME / AWAY / NEUTRAL)
    çıkar.
    Basit keyword mantığıyla başlıyoruz, ileride BERT/LLM ile güçlendirilir.
    """
    total_votes = {"OVER": 0.0, "UNDER": 0.0}
    spread_votes = {"HOME": 0.0, "AWAY": 0.0}
    total_ranges = []

    for pkt in packets:
        txt = pkt.raw_text.lower()
        w = pkt.trust_score or 0.5

        # Total:
        if "üst" in txt or "over" in txt:
            total_votes["OVER"] += w
        if "alt" in txt or "under" in txt:
            total_votes["UNDER"] += w

        # Basit barem yakalama: "226.5" gibi
        for m in re.finditer(r"(\d{3}\.\d)", txt):
            try:
                v = float(m.group(1))
                total_ranges.append(v)
            except ValueError:
                pass

        # Spread:
        # Bu aşamada çok basit: "ev sahibi kazanır" / "home team" / "Real Madrid win" gibi şeylere bakılabilir.
        if "ev sahibi" in txt or "home team" in txt:
            spread_votes["HOME"] += w
        if "deplasman" in txt or "away team" in txt:
            spread_votes["AWAY"] += w

    # consensus:
    def choose_consensus(votes: Dict[str, float]) -> str:
        if votes["OVER"] == votes.get("UNDER", 0) and "OVER" in votes:
            return "NEUTRAL"
        if "OVER" in votes:
            return max(votes, key=votes.get)
        if "HOME" in votes:
            return max(votes, key=votes.get)
        return "NEUTRAL"

    total_cons = choose_consensus(total_votes) if total_votes else "NEUTRAL"
    spread_cons = choose_consensus(spread_votes) if spread_votes else "NEUTRAL"

    if total_ranges:
        avg_barem = sum(total_ranges) / len(total_ranges)
        key_range = [avg_barem - 4.0, avg_barem + 4.0]
    else:
        avg_barem = None
        key_range = []

    total_view = {
        "consensus": total_cons,
        "avg_line": avg_barem,
        "key_range": key_range,
        "votes": total_votes,
    }

    spread_view = {
        "consensus": spread_cons,
        "votes": spread_votes,
    }

    return total_view, spread_view


def _estimate_soft_score_range(
    total_view: Dict,
    match_meta: MatchMeta,
) -> Dict:
    """
    total_view ve lig yapısına göre yumuşak skor aralığı tahmini.
    Şimdilik çıplak bir tahmin; ileride FAZ-13 istatistik motoru ile
    ortak çalışarak daha rafine hale gelecek.
    """
    # Eğer avg_line yoksa lig default'u kullan:
    if total_view.get("avg_line"):
        center = total_view["avg_line"]
    else:
        # EuroLeague için kabaca 160-170 arası; NBA için 220-230 arası kullanılabilir.
        if match_meta.league.lower() in {"euroleague", "euroleague basketball"}:
            center = 165.0
        else:
            center = 220.0

    return {
        "low": center - 8.0,
        "center": center,
        "high": center + 8.0,
    }


def normalize_packets(packets: List[RawNewsPacket], match_meta: MatchMeta) -> MatchNewsSummary:
    """
    Tüm RawNewsPacket listesi -> MatchNewsSummary
    """
    summary = MatchNewsSummary(
        match_key=match_meta.match_key,
        home_team=match_meta.home_team,
        away_team=match_meta.away_team,
    )

    if not packets:
        summary.confidence = 0.0
        summary.flags.append("NO_NEWS_DATA")
        return summary

    # Sakatlık:
    injuries = _extract_injury_info(packets, match_meta)
    summary.injuries = injuries

    # Total & Spread:
    total_view, spread_view = _extract_total_spread_view(packets)
    summary.total_view = total_view
    summary.spread_view = spread_view

    # Soft skor aralığı:
    summary.soft_score_range = _estimate_soft_score_range(total_view, match_meta)

    # Basit tempo çıkarımı (keyword bazlı):
    tempo_flags = {"HIGH": 0.0, "LOW": 0.0, "MID": 0.0}
    evidence = []

    for pkt in packets:
        txt = pkt.raw_text.lower()
        w = pkt.trust_score or 0.5
        if any(k in txt for k in ["yüksek tempo", "high-paced", "fastbreak", "run and gun"]):
            tempo_flags["HIGH"] += w
            evidence.append(f"[{pkt.source}] yüksek tempo sinyali")
        if any(k in txt for k in ["savunma maçı", "defensive battle", "low scoring"]):
            tempo_flags["LOW"] += w
            evidence.append(f"[{pkt.source}] düşük tempo sinyali")

    # consensus:
    tempo_hint = max(tempo_flags, key=tempo_flags.get) if any(tempo_flags.values()) else "MID"
    summary.tempo = {
        "pace_hint": tempo_hint,
        "evidence": evidence,
        "votes": tempo_flags,
    }

    # Flags & confidence:
    flags = []
    base_conf = 0.5  # haber varlığı

    if injuries.get("impact_home", 0) > 0.2 or injuries.get("impact_away", 0) > 0.2:
        flags.append("INJURY_RELEVANT")
        base_conf += 0.1

    if total_view.get("consensus") in ("OVER", "UNDER"):
        flags.append(f"TOTAL_{total_view['consensus']}")
        base_conf += 0.1

    if spread_view.get("consensus") in ("HOME", "AWAY"):
        flags.append(f"SPREAD_{spread_view['consensus']}")
        base_conf += 0.1

    if tempo_hint != "MID":
        flags.append(f"TEMPO_{tempo_hint}")
        base_conf += 0.05

    summary.flags = flags
    summary.confidence = min(1.0, base_conf)
    summary.sources_used = sorted({pkt.source for pkt in packets})

    # Şimdilik key_quotes boş; ileride önemli cümleleri seçip ekleyebilirsin.
    summary.key_quotes = []

    return summary


# =====================================================================
# 5) FEATURE ENCODER: SUMMARY -> SAYISAL ÖZELLİKLER
# =====================================================================

def encode_news_features(summary: MatchNewsSummary) -> Dict:
    """
    MatchNewsSummary'den FAZ-13 için sayısal özellik çıkar.
    Bunları istatistik motorunla birleştirip final skoru / baremi
    daha iyi kalibre edebilirsin.
    """
    injuries = summary.injuries or {}
    fatigue = summary.fatigue or {}
    tempo = summary.tempo or {}
    total_view = summary.total_view or {}
    spread_view = summary.spread_view or {}

    features = {
        # Sakatlık:
        "news_inj_impact_home": float(injuries.get("impact_home", 0.0)),
        "news_inj_impact_away": float(injuries.get("impact_away", 0.0)),

        # Yorgunluk (ileride NewsScraper + fixture verisi birleşince doldurulacak):
        "news_fatigue_diff": float(fatigue.get("fatigue_diff", 0.0)),

        # Tempo:
        "news_pace_high_flag": 1.0 if tempo.get("pace_hint") == "HIGH" else 0.0,
        "news_pace_low_flag": 1.0 if tempo.get("pace_hint") == "LOW" else 0.0,

        # Toplam sayı eğilimi:
        "news_total_over_flag": 1.0 if total_view.get("consensus") == "OVER" else 0.0,
        "news_total_under_flag": 1.0 if total_view.get("consensus") == "UNDER" else 0.0,
        "news_total_avg_line": float(total_view.get("avg_line") or 0.0),

        # Spread eğilimi:
        "news_spread_home_flag": 1.0 if spread_view.get("consensus") == "HOME" else 0.0,
        "news_spread_away_flag": 1.0 if spread_view.get("consensus") == "AWAY" else 0.0,

        # Genel:
        "news_confidence": float(summary.confidence or 0.0),
        "news_flag_injury_relevant": 1.0 if "INJURY_RELEVANT" in summary.flags else 0.0,
    }

    return features


# =====================================================================
# 6) ANA GİRİŞ: get_match_news
# =====================================================================

def get_match_news(match_meta: MatchMeta, use_cache: bool = True) -> Tuple[MatchNewsSummary, Dict]:
    """
    Dış dünyadan çağrılacak ana fonksiyon.

    DÖNEN:
        summary: MatchNewsSummary
        features: dict (encode_news_features)

    AKIŞ:
        1) Cache'te var mı? (ve çok eski değil mi?) -> varsa direkt dön.
        2) Yoksa:
            - fetch_raw_packets()
            - normalize_packets()
            - save_to_cache()
            - encode_news_features()
    """
    if use_cache:
        cached = load_from_cache(match_meta.match_key)
        if cached:
            log.info("NewsScraper: cache'den okundu: %s", match_meta.match_key)
            return cached, encode_news_features(cached)

    # Yeni veri çek:
    packets = fetch_raw_packets(match_meta)
    summary = normalize_packets(packets, match_meta)

    if use_cache:
        save_to_cache(summary)

    features = encode_news_features(summary)
    return summary, features


# =====================================================================
# 7) ÖRNEK KULLANIM (Test amaçlı)
# =====================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Örnek: Anadolu Efes vs Real Madrid maçı için meta:
    meta = MatchMeta(
        league="Euroleague",
        date="2025-12-04",
        home_team="Anadolu Efes",
        away_team="Real Madrid",
    )

    summary, feats = get_match_news(meta, use_cache=False)

    print("=== MatchNewsSummary ===")
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))

    print("\n=== news_features ===")
    print(json.dumps(feats, ensure_ascii=False, indent=2))
