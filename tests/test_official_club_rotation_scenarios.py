"""Actual source-claim -> player-minutes -> Bayesian/QMC numerical bridge.

All team/claim facts in these tests are SYNTHETIC. This is verification of
a calculation path, never evidence that a real NBA/EuroLeague/EuroCup
player is OUT or that the new model is calibrated.
"""
from copy import deepcopy
import hashlib
import math
import time
import pytest
from hybrid_engine import official_club_capture as cap

from core.team_identity import digest
from hybrid_engine.data import STRICT,feature_cut,Abstain
from hybrid_engine.models import HierarchicalStrength
from hybrid_engine.official_all_82_club_batch import load_all_82
from hybrid_engine.official_club_rotation_scenarios import (
    compare_verified_rotation,FORMAT,RESEARCH)


def scenario(league):
    pretty={"NBA":"NBA","EUROLEAGUE":"EuroLeague",
            "EUROCUP":"EuroCup"}[league]
    duration=48 if league=="NBA" else 40
    now=int(time.time())
    base=now-90*86400
    cohort=[];exposures={}
    for i in range(76):
        start=base+i*86400
        A_active=(i%3!=0)
        teams={"A":100+(18 if A_active else 0)+i%5,
               "B":105+i%4}
        home="A" if i%2 else "B"
        away="B" if home=="A" else "A"
        def quarters(points):
            return [points//4]*3+[points-(points//4)*3]
        row=dict(league=pretty,season="2026/2027",
            fixture_id="synthetic-"+str(i),fixture_start_utc=start,
            home_team_id=home,away_team_id=away,
            final_scores=[teams[home],teams[away]],
            periods=dict(home=quarters(teams[home]),
                         away=quarters(teams[away])),
            observed_at_utc=start+10000,
            ingested_at_utc=start+11000,
            source_catalog_sha256="a"*64)
        cohort.append([row])
        entry=dict(observed_at_utc=start-7200,
                   ingested_at_utc=start-7100)
        for side,team in (("home",home),("away",away)):
            ids=[f"{team}{j}" for j in range(6 if team=="A" else 5)]
            active=ids[:5] if team=="B" else (
                ids[:5] if A_active else ids[1:6])
            entry[side]=[dict(player_id=pid,
                              expected_minutes=duration if pid in active else 0)
                         for pid in ids]
        exposures[row["fixture_id"]]=entry
    cut=feature_cut(cohort,cohort[75][0],mode=STRICT)
    model=HierarchicalStrength().fit(
        [x[0] for x in cohort[:65]],
        cutoff_utc=cohort[69][0]["fixture_start_utc"],
        mode=STRICT,
        projected_exposures={k:v for k,v in exposures.items()
                             if int(k.split("-")[-1])<65})
    target=cut.target
    A_side="home" if target["home_team_id"]=="A" else "away"
    B_side="away" if A_side=="home" else "home"
    side_keys={
        "NBA":{"A":"nba_denver_nuggets","B":"nba_boston_celtics"},
        "EUROLEAGUE":{"A":"euroleague_olympiacos","B":"euroleague_zalgiris"},
        "EUROCUP":{"A":"eurocup_tofas","B":"eurocup_cedevita_olimpija"}
    }[league]
    lookup={r["club_key"]:r for r in load_all_82()}
    rosters={}
    for side,team in ((A_side,"A"),(B_side,"B")):
        ids=[f"{team}{j}" for j in range(6 if team=="A" else 5)]
        baseline=[dict(player_id=pid,
                       expected_minutes=duration if pid in ids[:5] else 0)
                  for pid in ids]
        adjusted=[dict(player_id=pid,
                       expected_minutes=duration if pid in (
                           ids[1:6] if team=="A" else ids[:5]) else 0)
                  for pid in ids]
        rosters[side]=dict(baseline=baseline,adjusted=adjusted)
    first=target["fixture_start_utc"]-1300
    observed=target["fixture_start_utc"]-900
    teamkey=side_keys["A"]
    report=dict(
        source_format="OFFICIAL_PLAYER_STATUS_SOURCE_V1",
        side=A_side,provider_player_id="A0",
        reported_status="OUT",reported_reason="PHYSICAL_INJURY",
        team_provider_id="A",club_key=teamkey,
        fixture_id=target["fixture_id"],
        source_url=lookup[teamkey]["official_news_entry_url"],
        document_sha256="a"*64,
        trusted_document_sha256="a"*64,
        player_identity_evidence_sha256="b"*64,
        published_at_utc=first-1000,
        first_captured_at_utc=first)
    capture=dict(format=cap.RECEIPT_FORMAT,club_key=teamkey,
        source_url=report["source_url"],body_sha256=report["document_sha256"],
        observed_at_utc=first-100,captured_at_utc=first)
    capture["receipt_sha256"]=hashlib.sha256(cap._packed(capture)).hexdigest()
    report["first_capture_receipt"]=capture
    feature=dict(
        format=FORMAT,league=league,season="2026/2027",
        fixture_id=target["fixture_id"],
        home_team_id=target["home_team_id"],
        away_team_id=target["away_team_id"],
        model_artifact_sha256=model.artifact_digest,
        observed_at_utc=observed,ingested_at_utc=observed+100,
        team_club_keys={A_side:side_keys["A"],B_side:side_keys["B"]},
        rosters=rosters,source_reports=[report])
    return model,cut,feature,target["fixture_start_utc"]-600


def _pins(feature):
    return {(r["side"],r["provider_player_id"]):r["document_sha256"]
            for r in feature["source_reports"]}


@pytest.mark.parametrize("league",["NBA","EUROLEAGUE","EUROCUP"])
def test_source_bound_synthetic_out_recalculates_real_10k_qmc_simulation(league):
    model,cut,feature,prediction_utc=scenario(league)
    r=compare_verified_rotation(model,cut,feature,
        trusted_feature_sha256=digest(feature),
        trusted_source_pins=_pins(feature),prediction_utc=prediction_utc)
    assert r["status"]==RESEARCH
    assert r["league"]==league
    assert r["method"]=="RQMC_HALTON"
    assert r["scenarios"]==10000
    assert r["injury_out_player_count"]==1
    assert r["training_historical_pregame_exposures_required"] is True
    assert r["baseline"]["total"]!=r["adjusted"]["total"]
    assert abs(r["deltas"]["total"])>0.00001
    assert sum(sum(q) for q in r["deltas"]["quarters"])==pytest.approx(
        r["deltas"]["total"],abs=1e-6)
    assert r["deltas"]["margin"]==pytest.approx(
        r["deltas"]["home"]-r["deltas"]["away"],abs=1e-7)
    assert r["baseline"]["metadata"]["player_effect"]=="PREMATCH_EXPOSURE_FITTED"
    assert r["adjusted"]["metadata"]["player_effect"]=="PREMATCH_EXPOSURE_FITTED"
    assert r["calculation_not_a_proven_accuracy_gain"] is True
    assert r["source_pin_independently_timestamp_attested"] is False
    assert r["model_input"] is False
    assert r["production_changed"] is False
    assert r["existing_forecast_modified"] is False


def test_false_injury_document_pin_and_after_forecast_capture_refused():
    model,cut,f,when=scenario("NBA")
    bad=_pins(f)
    bad[next(iter(bad))]="c"*64
    with pytest.raises(ValueError,match="INDEPENDENT_PLAYER_AND_SOURCE"):
        compare_verified_rotation(model,cut,f,
            trusted_feature_sha256=digest(f),trusted_source_pins=bad,prediction_utc=when)

    f["source_reports"][0]["first_captured_at_utc"]=when+1
    with pytest.raises(ValueError,match="FIRST_CAPTURE_RECEIPT_SCOPE_CONFLICT"):
        compare_verified_rotation(model,cut,f,
            trusted_feature_sha256=digest(f),trusted_source_pins=_pins(f),prediction_utc=when)


def test_wrong_fixture_player_and_gleague_assignment_refused():
    model,cut,f,when=scenario("NBA")
    f["source_reports"][0]["reported_reason"]="G_LEAGUE_ASSIGNMENT"
    with pytest.raises(ValueError,match="OFFICIAL_STATUS_PLAYER_OR_FIXTURE_BINDING"):
        compare_verified_rotation(model,cut,f,
            trusted_feature_sha256=digest(f),trusted_source_pins=_pins(f),prediction_utc=when)
    f["source_reports"][0]["reported_reason"]="PHYSICAL_INJURY"
    f["source_reports"][0]["fixture_id"]="wrong-other-game"
    with pytest.raises(ValueError,match="OFFICIAL_STATUS_PLAYER_OR_FIXTURE_BINDING"):
        compare_verified_rotation(model,cut,f,
            trusted_feature_sha256=digest(f),trusted_source_pins=_pins(f),prediction_utc=when)


def test_uncertified_player_status_and_unknown_lineups_abstain():
    model,cut,f,when=scenario("NBA")
    f["source_reports"]=[]
    with pytest.raises(Abstain,match="EXACT_SOURCE_AND_ID"):
        compare_verified_rotation(model,cut,f,
            trusted_feature_sha256=digest(f),trusted_source_pins=_pins(f),prediction_utc=when)
    model,cut,f,when=scenario("NBA")
    side=f["source_reports"][0]["side"]
    f["rosters"][side]["adjusted"][0]["expected_minutes"]=12
    with pytest.raises(Abstain,match="FIVE_PLAYER_MINUTE_BUDGET"):
        compare_verified_rotation(model,cut,f,
            trusted_feature_sha256=digest(f),trusted_source_pins=_pins(f),prediction_utc=when)


def test_no_player_trained_model_never_guess_points_by_injury_name():
    model,cut,f,when=scenario("NBA")
    model.players=[]
    with pytest.raises(Abstain,match="PLAYER_AWARE_OFFLINE_TRAINED_POSTERIOR_REQUIRED"):
        compare_verified_rotation(model,cut,f,
            trusted_feature_sha256=digest(f),trusted_source_pins=_pins(f),prediction_utc=when)


def test_feature_pin_mismatch_and_model_training_lookahead_refused():
    model,cut,f,when=scenario("EUROCUP")
    with pytest.raises(ValueError,match="PREGAME_ROTATION_INPUT_PIN_REQUIRED"):
        compare_verified_rotation(model,cut,f,
            trusted_feature_sha256="f"*64,trusted_source_pins=_pins(f),prediction_utc=when)
    with pytest.raises(ValueError,match="SOURCE_OR_MODEL_FIT_CUTOFF_LEAKAGE"):
        compare_verified_rotation(model,cut,f,
            trusted_feature_sha256=digest(f),trusted_source_pins=_pins(f),prediction_utc=model.cutoff)


def test_cross_league_club_misassignment_refused():
    model,cut,f,when=scenario("EUROLEAGUE")
    f["team_club_keys"]["home"]="nba_denver_nuggets"
    with pytest.raises(ValueError,match="ROTATION_CLUB_LEAGUE_MEMBERSHIP_MISMATCH"):
        compare_verified_rotation(model,cut,f,
            trusted_feature_sha256=digest(f),trusted_source_pins=_pins(f),prediction_utc=when)
