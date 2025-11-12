# main.py
# FAZ 3 – Ana çekirdek: veri akışı + simülasyon + sonuç gösterimi

from data_pipe import fetch_upcoming_mock
from sim_engine import simulate_game
from utils import log_event, format_game_result

def main():
    log_event("INFO", "Zeynal Core FAZ 3 başlatılıyor...")
    
    games = fetch_upcoming_mock()
    log_event("DEBUG", f"{len(games)} maç alındı (mock veri).")

    for game in games:
        log_event("INFO", f"{game.league}: {game.home} vs {game.away} simülasyon başlıyor...")
        result = simulate_game(game)
        print(format_game_result(game, result))

    log_event("INFO", "Tüm simülasyonlar tamamlandı ✅")

if __name__ == "__main__":
    main()
