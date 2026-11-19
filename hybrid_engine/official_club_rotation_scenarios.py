"""All-league verified-rotation -> actual Bayesian/QMC scenario bridge.

This is NOT a news-text-to-points heuristic. It reuses the trained
HierarchicalStrength player coefficients and the real 10k-path MC/QMC
forecast. A source report must have a pre-pinned content hash, correct
canonical fixture/player IDs, first-capture clock, and a full pair of
pregame projected five-player-minute exposure distributions. Without
an actually trained PLAYER-aware posterior, abstain.

Research SHADOW only: sources in the 82-team directory are NOT proof
of player status; tests use synthetic receipts. No existing predictions,
coefficients, training labels, Telegram or production archives are written.
"""
import math
from urllib.parse import urlsplit

from core.team_identity import digest
from hybrid_engine.data import Abstain
from hybrid_engine.distributions import Budget
from hybrid_engine.models import _exposure
from hybrid_engine.official_all_82_club_batch import load_all_82
from hybrid_engine.official_club_capture import verify_article_capture

FORMAT="OFFICIAL_PREGAME_VERIFIED_ROTATION_SCENARIOS_V1"
RESEARCH="SHADOW_NUMERICAL_ROTATION_COMPARISON_NOT_LIVE"
LEAGUES=frozenset(("NBA","EUROLEAGUE","EUROCUP"))
MAX_PLAYERS=20
MAX_REPORTS=12


def _same_host(a,b):
    x=urlsplit(a);y=urlsplit(b)
    return (x.scheme==y.scheme=="https" and
            x.hostname and y.hostname and
            x.hostname.removeprefix("www.")==
            y.hostname.removeprefix("www."))


def _players(rows,*,duration):
    if type(rows) is not list or not 5<=len(rows)<=MAX_PLAYERS:
        raise Abstain("COMPLETE_PREGAME_ROTATION_WITH_FIVE_ACTIVE_PLAYERS_REQUIRED")
    ids=set();total=0.
    result=[]
    for row in rows:
        if type(row) is not dict:
            raise ValueError("ROTATION_PLAYER_SCHEMA_INVALID")
        pid=row.get("player_id")
        minutes=row.get("expected_minutes")
        if (type(pid) is not str or not pid or len(pid)>128 or
            pid.strip()!=pid or pid in ids or
            type(minutes) not in (int,float) or
            not math.isfinite(minutes) or not 0<=minutes<=duration):
            raise ValueError("ROTATION_PLAYER_ID_OR_MINUTES_INVALID")
        ids.add(pid);total+=float(minutes)
        result.append(dict(player_id=pid,expected_minutes=float(minutes)))
    if abs(total-duration*5)>1e-6:
        raise Abstain("PREMATCH_FIVE_PLAYER_MINUTE_BUDGET_NOT_PROVEN")
    return result


def compare_verified_rotation(model,cut,feature,*,trusted_feature_sha256,
                              trusted_source_pins,prediction_utc,method="RQMC_HALTON"):
    """Numerically recompute BOTH simulations with common QMC/MC seed.

    Reporting difference does not mean the injury model is calibrated;
    source SHA supplied by caller is not independent timestamp attestation.
    """
    if (type(feature) is not dict or feature.get("format")!=FORMAT or
        type(trusted_feature_sha256) is not str or
        len(trusted_feature_sha256)!=64 or
        digest(feature)!=trusted_feature_sha256):
        raise ValueError("PREGAME_ROTATION_INPUT_PIN_REQUIRED")
    if (not model.fitted or not model.players or
        getattr(model,"artifact_digest",None)!=feature.get("model_artifact_sha256")):
        raise Abstain("PLAYER_AWARE_OFFLINE_TRAINED_POSTERIOR_REQUIRED")
    league=str(cut.target.get("league","")).upper()
    if (league not in LEAGUES or
        str(model.identity[0]).upper()!=league or
        cut.target["season"]!=feature.get("season") or
        model.identity[1]!=cut.target["season"] or
        not all(feature.get(k)==cut.target.get(k)
                for k in ("fixture_id","home_team_id","away_team_id")) or
        feature.get("league","").upper()!=league):
        raise ValueError("ROTATION_LEAGUE_SEASON_FIXTURE_IDENTITY_CONFLICT")
    tipoff=cut.target["fixture_start_utc"]
    observed=feature.get("observed_at_utc")
    ingested=feature.get("ingested_at_utc")
    if (type(prediction_utc) is not int or
        type(observed) is not int or type(ingested) is not int or
        not 0<observed<=ingested<=prediction_utc<=cut.cutoff_utc<tipoff or
        model.cutoff>=prediction_utc):
        raise ValueError("ROTATION_SOURCE_OR_MODEL_FIT_CUTOFF_LEAKAGE")
    sides=feature.get("team_club_keys")
    if type(sides) is not dict or set(sides)!={"home","away"}:
        raise ValueError("ROTATION_TEAM_CLUB_KEYS_REQUIRED")
    members={r["club_key"]:r for r in load_all_82()}
    for side in ("home","away"):
        key=sides[side]
        if key not in members or members[key]["league"]!=league:
            raise ValueError("ROTATION_CLUB_LEAGUE_MEMBERSHIP_MISMATCH")
    if sides["home"]==sides["away"]:
        raise ValueError("ROTATION_HOME_AWAY_SAME_CLUB")
    raw_rosters=feature.get("rosters")
    if type(raw_rosters) is not dict or set(raw_rosters)!={"home","away"}:
        raise ValueError("TWO_COMPLETE_ROTATIONS_REQUIRED")
    baseline={};adjusted={}
    absent={}
    for side in ("home","away"):
        r=raw_rosters[side]
        if type(r) is not dict or set(r)!={"baseline","adjusted"}:
            raise ValueError("BASELINE_AND_ADJUSTED_ROTATION_REQUIRED")
        duration=48 if league=="NBA" else 40
        baseline[side]=_players(r["baseline"],duration=duration)
        adjusted[side]=_players(r["adjusted"],duration=duration)
        b={x["player_id"]:x["expected_minutes"] for x in baseline[side]}
        a={x["player_id"]:x["expected_minutes"] for x in adjusted[side]}
        if set(b)!=set(a) or not set(b)<=set(model.players):
            raise Abstain("PLAYER_IDS_NOT_FITTED_OR_BASELINE_ROTATION_MISMATCH")
        absent[side]=[pid for pid in b if b[pid]>0 and a[pid]==0]
        if not absent[side] and b==a:
            continue
    if not any(absent.values()) or sum(map(len,absent.values()))>MAX_REPORTS:
        raise Abstain("EXPLICIT_INJURY_OUT_ROTATION_DISPLACEMENT_REQUIRED")
    source=feature.get("source_reports")
    if type(source) is not list or len(source)>MAX_REPORTS:
        raise ValueError("PRETIPOFF_OFFICIAL_PLAYER_REPORTS_REQUIRED")
    expected={(side,pid) for side in absent for pid in absent[side]}
    if (type(trusted_source_pins) is not dict or
        set(trusted_source_pins)!=expected):
        raise ValueError("INDEPENDENT_SOURCE_PINS_OUTSIDE_ROSTER_PAYLOAD_REQUIRED")
    found=set()
    for r in source:
        if type(r) is not dict:
            raise ValueError("OFFICIAL_PLAYER_SOURCE_SCHEMA")
        side=r.get("side")
        pid=r.get("provider_player_id")
        if (side,pid) not in expected or (side,pid) in found:
            raise ValueError("SOURCE_PLAYER_NOT_UNIQUELY_BOUND_TO_OUT_ROTATION")
        key=sides[side]
        member=members[key]
        source_url=r.get("source_url")
        expected_entry=member["official_news_entry_url"]
        if (type(source_url) is not str or not _same_host(source_url,expected_entry) or
            r.get("club_key")!=key or
            r.get("team_provider_id")!=cut.target[side+"_team_id"] or
            r.get("fixture_id")!=cut.target["fixture_id"] or
            r.get("reported_status")!="OUT" or
            r.get("reported_reason")!="PHYSICAL_INJURY" or
            r.get("source_format")!="OFFICIAL_PLAYER_STATUS_SOURCE_V1"):
            raise ValueError("OFFICIAL_STATUS_PLAYER_OR_FIXTURE_BINDING_INVALID")
        if league=="NBA":
            club_path=urlsplit(member["official_site_url"]).path.rstrip("/")
            raw_path=urlsplit(source_url).path
            if not (raw_path==club_path or
                    raw_path.startswith(club_path+"/")):
                raise ValueError("NBA_OFFICIAL_ARTICLE_WRONG_TEAM_PATH")
        sh=r.get("document_sha256");pinned=trusted_source_pins[(side,pid)]
        identity=r.get("player_identity_evidence_sha256")
        if (type(sh) is not str or len(sh)!=64 or
            sh!=pinned or type(identity) is not str or len(identity)!=64 or
            any(not x or any(c not in "0123456789abcdef" for c in x)
                for x in (sh,identity))):
            raise ValueError("INDEPENDENT_PLAYER_AND_SOURCE_DOCUMENT_PIN_REQUIRED")
        first=r.get("first_captured_at_utc")
        published=r.get("published_at_utc")
        receipt=r.get("first_capture_receipt")
        verify_article_capture(receipt)
        if (receipt["club_key"]!=key or
            receipt["source_url"]!=source_url or
            receipt["body_sha256"]!=sh or
            receipt["captured_at_utc"]!=first or
            receipt["observed_at_utc"]>observed):
            raise ValueError("OFFICIAL_ARTICLE_FIRST_CAPTURE_RECEIPT_SCOPE_CONFLICT")
        if (type(first) is not int or type(published) is not int or
            not 0<published<=receipt["observed_at_utc"]<=first<=observed<=prediction_utc or
            tipoff-published>72*3600):
            raise ValueError("PRE_FORECAST_FIRST_SOURCE_CAPTURE_CLOCK_REQUIRED")
        found.add((side,pid))
    if found!=expected:
        raise Abstain("OUT_PLAYERS_MUST_HAVE_EXACT_SOURCE_AND_ID_BINDING")
    base_input=dict(observed_at_utc=observed,ingested_at_utc=ingested,
                    home=baseline["home"],away=baseline["away"])
    adjust_input=dict(observed_at_utc=observed,ingested_at_utc=ingested,
                      home=adjusted["home"],away=adjusted["away"])
    # Run the real pregame player exposure validator, then the same
    # offline-fitted Bayesian posterior with the SAME QMC seed.
    duration=48 if league=="NBA" else 40
    _exposure(base_input,cut.cutoff_utc+1,duration)
    _exposure(adjust_input,cut.cutoff_utc+1,duration)
    if method not in ("RQMC_HALTON","MC"):
        raise ValueError("SUPPORTED_COMMON_RANDOM_SCENARIO_METHOD_REQUIRED")
    budget=Budget()
    first=model.predict(cut,method=method,
                        projected_exposure=base_input,
                        budget=budget,bounded_workspace=True)
    second=model.predict(cut,method=method,
                         projected_exposure=adjust_input,
                         budget=budget,bounded_workspace=True)
    initial=first.summary()
    injured=second.summary()
    return dict(format="OFFICIAL_CLUB_ROTATION_MATH_COMPARISON_V1",
        status=RESEARCH,league=league,season=feature["season"],
        fixture_id=feature["fixture_id"],
        source_input_sha256=trusted_feature_sha256,
        training_model_sha256=model.artifact_digest,
        source_captured_before_prediction=True,
        source_pin_independently_timestamp_attested=False,
        training_historical_pregame_exposures_required=True,
        method=method,scenarios=len(first.samples),
        baseline=initial,adjusted=injured,
        deltas=dict(
            home=injured["home"]-initial["home"],
            away=injured["away"]-initial["away"],
            total=injured["total"]-initial["total"],
            margin=injured["margin"]-initial["margin"],
            quarters=[[injured["quarters"][q][s]-initial["quarters"][q][s]
                       for s in range(2)] for q in range(4)]),
        injury_out_player_count=sum(map(len,absent.values())),
        source_reports_replayed=len(source),
        calculation_not_a_proven_accuracy_gain=True,
        model_input=False,production_changed=False,
        existing_forecast_modified=False,
        historical_data_modified=False,requests=0)
