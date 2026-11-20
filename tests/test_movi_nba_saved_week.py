"""Offline saved week parsing tests, no HTTP, archive writes, or credentials."""
import pytest
from hybrid_engine.movi_nba_saved_week import import_saved_report


def sample():
    return """
DURUM: OK
KAYNAK: ESPN fikstür referansı (NBA resmî servis değildir)
MOVIODDS EK API ISTEK: 0
ESPN API ISTEK: 8
HAFTA (TSI): 2026-11-21 - 2026-11-27
NBA TOPLAM: 3 | MOVIODDS KATALOG ESLESME: 1 | KATALOGDA OLMAYAN: 2

2026-11-21 (TSI) | ESPN MAC: 2
03:00 Charlotte Hornets @ Atlanta Hawks [M+] | MOVI_SAAT_FARKI:10.0dk
21:00 Milwaukee Bucks @ Philadelphia 76ers [M-]

2026-11-22 (TSI) | ESPN MAC: 1
03:30 Portland Trail Blazers @ New York Knicks [M-]
M+ = kayitli MoviOdds katalogunda; M- = kayitli katalogda bulunmuyor.
Bu isaretler guncel oran var/yok anlami tasimaz.
"""


def test_import_saved_report_uses_tsi_and_never_claims_fresh():
    obj = import_saved_report(sample())
    assert obj["status"] == "OK"
    assert obj["count"] == 3
    assert obj["network_calls"] == 0
    assert obj["moviodds_saved_catalog_matched"] == 1
    assert obj["moviodds_saved_catalog_missing"] == 2
    assert obj["games"][0]["utc"] == "2026-11-21T00:00:00+00:00"
    assert obj["games"][0]["moviodds_kickoff_delta_minutes"] == 10.0
    assert all(x["live_market_price_status"] == "NOT_VERIFIED" for x in obj["games"])


def test_report_rejects_bad_totals():
    with pytest.raises(ValueError, match="INCOMPLETE_WEEK_REPORT"):
        import_saved_report(sample().replace("NBA TOPLAM: 3", "NBA TOPLAM: 4").replace("KATALOGDA OLMAYAN: 2", "KATALOGDA OLMAYAN: 3"))


def test_report_rejects_bad_day_count():
    with pytest.raises(ValueError, match="INCOMPLETE_DAY_REPORT"):
        import_saved_report(sample().replace("ESPN MAC: 2", "ESPN MAC: 1"))


def test_report_rejects_unknown_team():
    with pytest.raises(ValueError, match="UNKNOWN_OR_DUPLICATE_TEAM"):
        import_saved_report(sample().replace("Charlotte Hornets", "Impossible Basketball Team"))


def test_report_rejects_wrong_status():
    with pytest.raises(ValueError, match="UNVERIFIED_REPORT_STATUS"):
        import_saved_report(sample().replace("DURUM: OK", "DURUM: BAD"))


def test_report_rejects_duplicate_matchup():
    duplicated = sample().replace("21:00 Milwaukee Bucks @ Philadelphia 76ers [M-]",
                                  "21:00 Charlotte Hornets @ Atlanta Hawks [M-]")
    with pytest.raises(ValueError, match="DUPLICATE_FIXTURE"):
        import_saved_report(duplicated)
