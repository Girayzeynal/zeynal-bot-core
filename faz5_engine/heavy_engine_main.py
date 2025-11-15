"""
FAZ-5 Heavy Engine Ana Modül
Her mod çalıştırıldığında bu dosya devreye girer.
MatchPack → EngineCore → EngineRouter zincirini yönetir.
"""

from engine_core import EngineCore
from engine_router import route_mode
from match_pack import MatchPack, TeamPack


def run_heavy_engine(mode="standard"):
    """
    FAZ-5 motorunu seçilen moda göre çalıştırır.
    Dönüş: string (Telegram için hazır metin)
    """
    core = EngineCore()
    mode_info = route_mode(mode)

    # Örnek dummy paket:
    home = TeamPack(code="LAL", pts=110, pace=102, power=78)
    away = TeamPack(code="BOS", pts=104, pace=99, power=75)
    match = MatchPack(home, away)

    result = core.evaluate_match(match, mode_info)

    text = f"""
🔥 *FAZ-5 Heavy Engine Çalıştırıldı*
🎯 Mod: {mode}
————————————
🏀 {home.code} vs {away.code}
📊 Tahmini Skor: {result['score_est']}
⚡ Tempo (Pace): {result['pace']}
🎯 Güç Dengesi: {result['power_diff']}
🏆 Tahmini Kazanan: {result['winner']}
————————————
"""
    return text


def main():
    print(run_heavy_engine("standard"))


if __name__ == "__main__":
    main()
