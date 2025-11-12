# utils.py
# FAZ 3 – Yardımcı fonksiyonlar (timestamp, renkli log, formatlayıcı)

from datetime import datetime, timezone

def utc_timestamp():
    """Gerçek zamanlı UTC zaman damgası döndürür."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def log_event(level, message):
    """Renkli terminal logu (DEBUG / INFO / ERROR)"""
    colors = {"DEBUG": "\033[94m", "INFO": "\033[92m", "ERROR": "\033[91m"}
    reset = "\033[0m"
    color = colors.get(level.upper(), "")
    print(f"{color}[{utc_timestamp()}] [{level}] {message}{reset}")

def format_game_result(game, result):
    """Simülasyon sonucunu sade metin haline getirir."""
    return (
        f"🏀 {game.league} | {game.home} vs {game.away}\n"
        f"🧮 Tahmin: {result['pick']}\n"
        f"📊 Olasılık: %{result['home_prob']*100:.1f}\n"
        f"🎯 Güven: %{result['confidence']*100:.1f}\n"
        f"🔢 Toplam ort.: {result['total_avg']} ±{result['total_std']}\n"
    )
