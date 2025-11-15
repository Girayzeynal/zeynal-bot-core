"""
FAZ-5 Heavy Engine – MatchPack
FAZ-4 NBA modellerinden gelen veriyi FAZ-5 çekirdeğine uygun yapıya çevirir.
"""


class TeamPack:
    """
    Takımın FAZ-5 işlemine uygun sadeleştirilmiş formu
    """
    def __init__(self, code, pts=0, pace=100, power=50):
        self.code = code
        self.pts = pts
        self.pace = pace
        self.power = power


class MatchPack:
    """
    Tek maç için iki takımın FAZ-5 formatına çevrilmiş paketi
    """
    def __init__(self, home: TeamPack, away: TeamPack):
        self.home = home
        self.away = away
