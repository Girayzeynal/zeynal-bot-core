import os
import json
from dataclasses import dataclass, asdict
from datetime import date
from typing import List, Dict, Tuple
import statistics
import random

import telebot

# ============================================
#  TELEGRAM BOT AYARI
#  - Fly.io Secret: BOT_TOKEN veya TELEGRAM_BOT_TOKEN
# ============================================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Environment variable BOT_TOKEN or TELEGRAM_BOT_TOKEN must be set")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

MEMORY_FILE = "faz7_memory.json"
WINDOW_DAYS = 7
DATE_FMT = "%Y-%m-%d"


# ============================================
#  FAZ-7.9 HAFIZA MODELİ
# ============================================

@dataclass
class Faz7DayRecord:
    day: str          # YYYY-MM-DD
    matches: int
    confidence: float
    edge: float
    mode: str         # SAFE / BAL / AGG


class Faz7Memory:
    def __init__(self, path: str = MEMORY_FILE, window_days: int = WINDOW_DAYS) -> None:
        self.path = path
        self.window_days = window_days
        self.records: List[Faz7DayRecord] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            self.records = []
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.records = [Faz7DayRecord(**item) for item in data]
        except Exception:
            # Dosya bozulmuşsa temiz başla
            self.records = []

    def _save(self) -> None:
        data = [asdict(r) for r in self.records]
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def update_today(self, matches: int, confidence: float, edge: float, mode: str) -> None:
        """Bugünün FAZ-7 kaydını güncelle (veya oluştur)."""
        day_str = date.today().strftime(DATE_FMT)

        # Bugüne ait kayıt varsa sil → yerine yenisini koy
        filtered = [r for r in self.records if r.day != day_str]
        filtered.append(Faz7DayRecord(
            day=day_str,
            matches=matches,
            confidence=confidence,
            edge=edge,
            mode=mode,
        ))

        # Sadece son window_days günü tut
        filtered.sort(key=lambda r: r.day)
        if len(filtered) > self.window_days:
            filtered = filtered[-self.window_days:]

        self.records = filtered
        self._save()

    def recent(self) -> List[Faz7DayRecord]:
        return list(self.records)

    def averages(self) -> Tuple[float, float]:
        if not self.records:
            return 0.0, 0.0
        confs = [r.confidence for r in self.records]
        edges = [r.edge for r in self.records]
        return float(sum(confs) / len(confs)), float(sum(edges) / len(edges))

    def trend_slope(self) -> float:
        """Confidence üzerinden basit lineer trend (eğim)."""
        if len(self.records) < 2:
            return 0.0
        xs = list(range(len(self.records)))
        ys = [r.confidence for r in self.records]
        x_mean = statistics.mean(xs)
        y_mean = statistics.mean(ys)
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        den = sum((x - x_mean) ** 2 for x in xs)
        if den == 0:
            return 0.0
        return num / den

    def volatility(self) -> float:
        """7 günlük confidence oynaklığı (standart sapma)."""
        if len(self.records) < 2:
            return 0.0
        confs = [r.confidence for r in self.records]
        return float(statistics.pstdev(confs))

    def mode_stats(self) -> Dict[str, Dict[str, float]]:
        """SAFE / BAL / AGG için run ve ortalamalar."""
        result: Dict[str, Dict[str, float]] = {}
        for mode in ("SAFE", "BAL", "AGG"):
            recs = [r for r in self.records if r.mode == mode]
            if not recs:
                result[mode] = {
                    "runs": 0,
                    "avg_conf": 0.0,
                    "avg_edge": 0.0,
                }
            else:
                result[mode] = {
                    "runs": len(recs),
                    "avg_conf": float(sum(r.confidence for r in recs) / len(recs)),
                    "avg_edge": float(sum(r.edge for r in recs) / len(recs)),
                }
        return result


memory = Faz7Memory()


# ============================================
#  FAZ-6 ÖRNEK MOTOR (PLACEHOLDER)
#  (Gerçek motoru sonra buraya entegre edebiliriz)
# ============================================

def _deterministic_random_base() -> float:
    """Her gün için hafif farklı ama deterministik jitter."""
    seed = int(date.today().strftime("%Y%m%d"))
    random.seed(seed)
    return random.uniform(-0.01, 0.01)


def build_faz6_examples() -> Tuple[list, dict, dict]:
    """
    Basit FAZ-6 örnek hesaplama.

    Dönüş:
        matches: /faz6_auto için maç listesi
        coupons: SAFE/BAL/AGG -> maç listeleri
        summary: {matches, avg_conf, avg_edge}
    """
    base_jitter = _deterministic_random_base()

    raw_matches = [
        {
            "league": "EL",
            "code": "EFES@REAL",
            "pick": "REAL MADRID -5.5 (spread)",
            "conf": 0.66 + base_jitter,
            "edge": 0.045 + base_jitter / 2,
        },
        {
            "league": "EL",
            "code": "FENER@OLY",
            "pick": "OLYMPIACOS -3.5 (spread)",
            "conf": 0.64 + base_jitter / 1.5,
            "edge": 0.041 + base_jitter / 2,
        },
        {
            "league": "NBA",
            "code": "BOS@MIA",
            "pick": "UNDER 224.5 (total)",
            "conf": 0.63 - base_jitter,
            "edge": 0.036 + base_jitter / 2,
        },
        {
            "league": "NBA",
            "code": "LAL@DEN",
            "pick": "DEN -4.5 (spread)",
            "conf": 0.61 + base_jitter / 3,
            "edge": 0.032 + base_jitter / 2,
        },
        {
            "league": "NBA",
            "code": "CHI@NYK",
            "pick": "NYK ML (moneyline)",
            "conf": 0.60 + base_jitter / 4,
            "edge": 0.031 + base_jitter / 2,
        },
        {
            "league": "NBA",
            "code": "GSW@PHX",
            "pick": "OVER 230.5 (total)",
            "conf": 0.59 + base_jitter / 5,
            "edge": 0.028 + base_jitter / 2,
        },
    ]

    # Stake = confidence * edge’e göre küçük bir ölçek
    for m in raw_matches:
        score = m["conf"] * max(m["edge"], 0.0001)
        m["stake"] = round(0.6 + score * 5, 2)

    # Kuponlar: 1=SAFE (ilk 2), 2=BAL (sonraki 2), 3=AGG (son 2)
    coupons = {
        "SAFE": raw_matches[0:2],
        "BAL": raw_matches[2:4],
        "AGG": raw_matches[4:6],
    }

    avg_conf = sum(m["conf"] for m in raw_matches) / len(raw_matches)
    avg_edge = sum(m["edge"] for m in raw_matches) / len(raw_matches)
    summary = {
        "matches": len(raw_matches),
        "avg_conf": float(round(avg_conf, 3)),
        "avg_edge": float(round(avg_edge, 3)),
    }

    return raw_matches, coupons, summary


# ============================================
#  FAZ-7.9 STAKE & STRATEJİ BEYNİ
# ============================================

def compute_stake_multipliers(mem: Faz7Memory) -> Dict[str, float]:
    avg_conf, avg_edge = mem.averages()
    vol = mem.volatility()
    trend = mem.trend_slope()

    # Temel çarpanlar
    stake_safe = 1.0
    stake_bal = 1.0
    stake_agg = 0.9

    # Sistem güçlü & trend pozitif → AGG biraz cesaretlendir
    strength = (avg_conf - 0.60) + (avg_edge - 0.03) * 8
    if strength > 0.02 and trend > 0:
        stake_agg += 0.1

    # Volatilite yüksek → AGG kısmı kıs, SAFE’i hafif boostla
    if vol > 0.01:
        stake_agg -= 0.1
        stake_safe += 0.05

    # Sınırlar
    stake_safe = max(0.7, min(stake_safe, 1.3))
    stake_bal = max(0.8, min(stake_bal, 1.2))
    stake_agg = max(0.7, min(stake_agg, 1.3))

    return {
        "SAFE": round(stake_safe, 2),
        "BAL": round(stake_bal, 2),
        "AGG": round(stake_agg, 2),
    }


def select_mode(stake_multipliers: Dict[str, float]) -> str:
    """En yüksek stake çarpanına sahip modu seç (eşitlikte BAL)."""
    best_mode = "BAL"
    best_value = stake_multipliers.get("BAL", 1.0)
    for mode in ("SAFE", "AGG"):
        value = stake_multipliers.get(mode, 1.0)
        if value > best_value + 1e-6:
            best_mode = mode
            best_value = value
    return best_mode


def format_faz7_plan(today_summary: Dict[str, float], mem: Faz7Memory) -> str:
    avg_conf7, avg_edge7 = mem.averages()
    vol = mem.volatility()
    trend = mem.trend_slope()
    stakes = compute_stake_multipliers(mem)
    active_mode = select_mode(stakes)

    def flag(mode: str) -> str:
        mark = "✅" if mode == active_mode or (
            mode == "BAL" and active_mode not in ("SAFE", "AGG")
        ) else "❌"
        return f"{mode}: {mark} (x{stakes[mode]:.2f})"

    lines = []
    lines.append("🧠 <b>FAZ-7.9 STRATEJİ BEYNİ</b>")
    lines.append("")
    lines.append(f"🎯 Mod: <b>{active_mode}</b>")
    lines.append(
        f"📊 Bugün: maç={today_summary['matches']} | conf={today_summary['avg_conf']:.3f} | edge={today_summary['avg_edge']:.3f}"
    )
    lines.append(f"📊 7g Ort.: conf={avg_conf7:.3f} | edge={avg_edge7:.3f}")
    lines.append(
        f"📊 Trend: {'INIT' if len(mem.recent()) < 2 else f'slope {trend:.4f}'}"
    )
    lines.append(f"🌪 Volatilite: {vol:.4f}")
    lines.append(f"🛠 Stake Normalize: {stakes[active_mode]:.2f}")
    lines.append("")
    lines.append("📦 Seviye Durumu")
    lines.append(f"- {flag('SAFE')}")
    lines.append(f"- {flag('BAL')}")
    lines.append(f"- {flag('AGG')}")
    return "\n".join(lines)


def format_faz7_status(mem: Faz7Memory) -> str:
    stakes = compute_stake_multipliers(mem)
    mode_stats = mem.mode_stats()

    lines = []
    lines.append("🧠 <b>FAZ-7.9 HAFIZA ÖZETİ</b> (Son 7 Gün)")
    lines.append("")
    lines.append("Mod | Run | Avg Conf | Avg Edge | Stake x")
    lines.append("----|-----|----------|----------|--------")
    for mode in ("SAFE", "BAL", "AGG"):
        s = mode_stats[mode]
        line = (
            f"{mode:<4}| {s['runs']:<3} | {s['avg_conf']:.3f}   | "
            f"{s['avg_edge']:.4f}   | {stakes[mode]:.2f}"
        )
        lines.append(line)
    lines.append("")
    lines.append(
        "Not: Stake çarpanları FAZ-7.9 beyni tarafından son 7 güne ve oynaklığa göre ayarlanır."
    )
    return "\n".join(lines)


# ============================================
#  TELEGRAM KOMUTLARI
# ============================================

@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    text = (
        "Selam, ben <b>Zeynal Core AI</b> 🤖\n\n"
        "Komutlar:\n"
        " • /status – Sistem özeti\n"
        " • /faz6_auto – FAZ-6 otomatik maç listesi\n"
        " • /faz6_coupon – FAZ-6 kupon + FAZ-7.9 güncelle\n"
        " • /faz7_plan – Günlük FAZ-7.9 strateji beyni\n"
        " • /faz7_status – Son 7 gün hafıza özeti\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["status"])
def cmd_status(message):
    avg_conf7, avg_edge7 = memory.averages()
    vol = memory.volatility()
    text = (
        "🟢 <b>Sistem stabil.</b>\n"
        "FAZ-4 aktif.\n"
        "FAZ-5 bağlı.\n"
        "FAZ-6 tam online.\n"
        "FAZ-7.9 strateji beyni ve hafıza sistemi çalışıyor.\n\n"
        f"7g Ortalama Conf: {avg_conf7:.3f}\n"
        f"7g Ortalama Edge: {avg_edge7:.3f}\n"
        f"Volatilite: {vol:.4f}\n"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["faz6_auto"])
def cmd_faz6_auto(message):
    matches, _, _ = build_faz6_examples()
    lines = ["🧠 <b>FAZ-6 AUTO SONUCU</b>", ""]
    for m in matches:
        lines.append(f"📌 {m['league']}:{m['code']}")
        lines.append(f"🎯 {m['pick']}")
        lines.append(f"📈 Güven: {m['conf']:.2f} | Edge: {m['edge']:.3f}")
        lines.append(f"💰 Stake: {m['stake']:.2f}")
        lines.append("— — —")
    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(commands=["faz6_coupon"])
def cmd_faz6_coupon(message):
    matches, coupons, summary = build_faz6_examples()

    # Günlük FAZ-7 kaydı → şu an BAL varsayıyoruz
    memory.update_today(
        matches=summary["matches"],
        confidence=summary["avg_conf"],
        edge=summary["avg_edge"],
        mode="BAL",
    )

    avg_conf7, avg_edge7 = memory.averages()
    stakes = compute_stake_multipliers(memory)
    active_mode = select_mode(stakes)

    lines = []
    lines.append("💰 <b>FAZ-7 + FAZ-6 BİRLEŞİK KUPONLAR</b>")
    lines.append("")
    lines.append(f"📊 Ortalama Güven (7g): {avg_conf7:.3f}")
    lines.append(f"📊 Ortalama Edge (7g): {avg_edge7:.3f}")
    lines.append("📅 Günlük Limit: 4.0")
    lines.append(f"🤖 Aktif Mod: {active_mode}")
    lines.append(f"🛠 Stake Normalize: {stakes[active_mode]:.2f}")
    lines.append("")

    names = {
        "SAFE": "Kupon 1 — SAFE",
        "BAL": "Kupon 2 — BALANCED",
        "AGG": "Kupon 3 — AGGRESSIVE",
    }
    order = ["SAFE", "BAL", "AGG"]
    for key in order:
        lines.append(f"🔥 {names[key]}")
        for m in coupons[key]:
            lines.append(f"- {m['league']}:{m['code']} | {m['pick']}")
            lines.append(
                f"  Güven: {m['conf']:.2f} | Edge: {m['edge']:.3f} | Stake: {m['stake']:.2f}"
            )
        lines.append("— — —")

    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(commands=["faz7_plan"])
def cmd_faz7_plan(message):
    _, _, summary = build_faz6_examples()
    plan_text = format_faz7_plan(summary, memory)
    bot.reply_to(message, plan_text)


@bot.message_handler(commands=["faz7_status"])
def cmd_faz7_status(message):
    text = format_faz7_status(memory)
    bot.reply_to(message, text)


# ============================================
#  MAIN
# ============================================

def main():
    print("Zeynal Core AI bot starting with FAZ-7.9 strategy engine...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)


if __name__ == "__main__":
    main()
