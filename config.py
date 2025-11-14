# -----------------------------
# FAZ-4 GLOBAL CONFIG
# HoopBrain (Zeynal Bot Core)
# -----------------------------

# Telegram Bot Token
BOT_TOKEN = "TELEGRAM_BOT_TOKENI_BURAYA_YAZ"

# NBA DATA PROVIDER URL
NBA_API_URL = "https://api.nba.com/stats/teams"

# Veri yenileme süresi (saniye)
REFRESH_INTERVAL = 60   # Her 1 dakika güncelle

# Dosya yolları
NBA_CACHE_FILE = "nba_cache.json"

# Log ayarları
ENABLE_LOGS = True

# Güvenlik (API hata denemesi sınırı)
MAX_RETRY = 3
RETRY_SLEEP = 1.5
