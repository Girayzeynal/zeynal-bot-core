"""Synthetic-only regression tests for the read-only three-league Telegram view."""
from hybrid_engine.unified_results_view import (
    LEAGUES,normalized_rows,render_all,render_performance,summary,unwrap
)


def row(league, fixture, start, *, model="MODEL", actual=None, legacy=False):
    item = dict(league=league,season="2026/2027",fixture_id=fixture,
                fixture_start_utc=start,home="HOME",away="AWAY",
                model_version=model,model_digest="digest-"+model,
                prediction=[80., 90.],actual=actual)
    if legacy:
        item["legacy_publication_clock_unrecorded"] = True
    return item


def test_unified_three_leagues_scope_and_dedup():
    now = 1000
    nba = dict(status="VERIFIED_LIVE_REPORT",
               forecasts=[row("NBA","n1",100,actual=[79,92]),
                          row("NBA","n2",1500)],
               groups=[dict(model_version="NBA_V1",n=1,team_mae=2.,
                            total_mae=1.)])
    euroleague = dict(status="VERIFIED_LIVE_REPORT",
                      forecasts=[row("EUROLEAGUE","e1",100,model="BAYES",actual=[83,79],legacy=True),
                                 row("EUROLEAGUE","e1",100,model="FAZ13",actual=[83,79],legacy=True)],
                      groups=[])
    eurocup = dict(status="VERIFIED_LIVE_REPORT",
                   forecasts=[row("EUROCUP","u1",900)],
                   groups=[])
    data = dict(NBA=nba,EUROLEAGUE=dict(report=euroleague),EUROCUP=eurocup)
    assert summary(nba,"NBA",now)==dict(league="NBA",archived=2,matched=1,
                                         started_unverified=0,not_started=1)
    assert len(normalized_rows(euroleague,"EUROLEAGUE"))==1
    text=render_all(data,now=now)
    assert "TOPLAM: 2 eşleşmiş / 4 kayıt" in text
    assert text.count("HOME – AWAY | FINAL")==2
    assert "BAŞLADI; FINAL KANITI YOK" in text
    assert "ilk yayın zamanı kanıtlanmadı" in text
    assert "→ 83–79" in text
    quality=render_performance(data)
    assert "NBA_V1" in quality
    assert "ESKİ" not in quality


def test_quarter_and_half_error_and_overtime_scope():
    periods=dict(home=[20,20,20,20,10],away=[20,20,20,20,10])
    q=[[21,21],[21,21],[21,21],[21,21]]
    case=row("NBA","n",100,actual=[80,80])
    case.update(predicted_quarters=q,actual_periods=periods,final_with_ot=[90,90],
                prediction=[84,84])
    data={code:dict(status="VERIFIED_LIVE_REPORT",
                    forecasts=[case] if code=="NBA" else [],groups=[]) for code in LEAGUES}
    text=render_all(data,now=1000)
    assert "1Q +2.0" in text and "2H +4.0" in text
    assert "Uzatma dahil: [90, 90]" in text
    assert "Toplam hata +8.00" in text


def test_wrong_league_never_counted():
    bad=dict(status="VERIFIED_LIVE_REPORT",forecasts=[row("EUROCUP","x",100)],groups=[])
    try:
        normalized_rows(bad,"NBA")
    except ValueError as exc:
        assert str(exc)=="UNIFIED_LEAGUE_IDENTITY_CONFLICT"
    else:
        raise AssertionError("wrong league was accepted")
    assert unwrap(dict(report=dict(report=bad)))==bad
