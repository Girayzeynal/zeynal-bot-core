"""Cross NBA.com team ID namespace to ESPN *from a pinned season snapshot*.

No hard-coded NBA.com-to-ESPN numeric ID guesses, no fuzzy names or
post-forecast membership backfills. Replays the existing immutable source
snapshot through TeamIdentityRegistry; its SHA MUST be pinned by the caller
independently of the snapshot supplied here.

The result is a team-namespace mapping candidate for research/shadow only.
It is NOT proof of fixture ID, player ID, injury truth or model eligibility.
"""
from core.team_identity import TeamIdentityRegistry, IdentityRefusal
from core.league_identity import resolve_league

FORMAT="OFFICIAL_NBA_ESPN_TEAM_CROSSWALK_RESEARCH_V1"
ALLOWED=frozenset(("nba_denver_nuggets","nba_boston_celtics"))


def audit_nba_team_crosswalk(club,participants_snapshot,*,trusted_snapshot_sha256,
                             asof_utc):
    if type(club) is not dict or club.get("club_key") not in ALLOWED or (
        club.get("league")!="NBA" or
        type(club.get("native_team_id")) is not str or
        not club["native_team_id"].startswith("16106127") or
        type(club.get("name")) is not str or not club["name"].strip()):
        raise ValueError("NBA_CROSSWALK_CLUB_NOT_IN_RESEARCH_PILOT")
    if type(asof_utc) is not int or asof_utc<=0:
        raise ValueError("NBA_CROSSWALK_ASOF_UTC_REQUIRED")
    if (not isinstance(trusted_snapshot_sha256,str) or
        len(trusted_snapshot_sha256)!=64):
        raise ValueError("INDEPENDENTLY_PINNED_SEASON_SNAPSHOT_REQUIRED")
    if (type(participants_snapshot) is not dict or
        participants_snapshot.get("sha256")!=trusted_snapshot_sha256):
        raise ValueError("PARTICIPANT_SNAPSHOT_TRUST_ANCHOR_REQUIRED")
    reg=TeamIdentityRegistry()
    reg.ingest(participants_snapshot,trusted_sha256=trusted_snapshot_sha256)
    p=participants_snapshot["payload"]
    if (p["season_id"]!="2026/2027" or p["league_id"]!="NBA" or
        p["ingested_at_utc"]>asof_utc or
        resolve_league("NBA").provider!="ESPN"):
        raise ValueError("SEASON_SOURCE_NOT_AVAILABLE_AT_FORECAST_CUTOFF")
    try:
        teams=reg.participants("NBA","2026/2027",asof_utc=asof_utc)
    except IdentityRefusal as exc:
        raise ValueError("NBA_PARTICIPANT_CUTOFF_NOT_COVERED") from exc
    # Exact official provider name only. A shared city, substring or fuzzy
    # alias is NOT enough to prove cross-provider identity.
    matches=[t for t in teams if t.official_name==club["name"]]
    if len(matches)!=1:
        raise ValueError("NBA_ESP_TEAM_NAME_NOT_UNIQUELY_MATCHED")
    t=matches[0]
    if len(t.provider_ids)!=1 or t.provider_ids[0][0]!="ESPN":
        raise ValueError("NBA_ESP_PROVIDER_NAMESPACE_MISMATCH")
    return dict(format=FORMAT,
                status="SOURCE_PINNED_TEAM_CROSSWALK_CANDIDATE_ONLY",
                club_key=club["club_key"],league="NBA",season="2026/2027",
                nba_com_team_id=club["native_team_id"],
                espn_team_id=t.provider_ids[0][1],
                source_name=t.official_name,
                source_participant_snapshot_sha256=trusted_snapshot_sha256,
                source_participant_ingested_at_utc=p["ingested_at_utc"],
                asof_utc=asof_utc,
                provider_namespace="ESPN",
                verified_fixture_id=None,verified_player_id=None,
                no_fuzzy_matching=True,
                source_attestation="LOCAL_HASH_NOT_INDEPENDENT_PROVIDER_SIGNATURE",
                model_input=False,production_changed=False)
