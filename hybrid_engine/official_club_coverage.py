"""2026/27 club coverage inventory — members are NOT connected news providers.

One canonical 82-team inventory, with only the six *actually* observed
opt-in news page sources inherited from the pinned pilot manifest.
All other official URLs are NULL. This code never infers domains from
team names, invents roster status, fetches websites or provides model inputs.
"""
import argparse
import json
from pathlib import Path

from hybrid_engine.official_club_sources import registry

INVENTORY=Path(__file__).with_name("official_club_coverage_2026_27.json")
COUNTS={"NBA":30,"EUROLEAGUE":20,"EUROCUP":32}
FORMAT="OFFICIAL_CLUB_SEASON_2026_27_COVERAGE_V1"


def load_coverage(path=INVENTORY):
    doc=json.loads(Path(path).read_text(encoding="utf-8"))
    teams=doc.get("teams")
    if (doc.get("format")!=FORMAT or doc.get("season")!="2026/2027"
        or type(teams) is not list or len(teams)!=sum(COUNTS.values())):
        raise ValueError("CLUB_2026_27_COVERAGE_INVENTORY_INVALID")
    pilot={x["club_key"]:x for x in registry()}
    seen=set()
    league_counts={k:0 for k in COUNTS}
    observed_counts={k:0 for k in COUNTS}
    for row in teams:
        if (type(row) is not dict or
            not {"league","team_name","club_key","official_news_url",
                 "status","membership_evidence_url","native_team_id"}<=row.keys()):
            raise ValueError("COVERAGE_ENTRY_INVALID")
        league=row["league"];key=row["club_key"]
        if (league not in COUNTS or type(key) is not str or not key or
            key in seen or type(row["team_name"]) is not str or
            not row["team_name"].strip()):
            raise ValueError("CLUB_COVERAGE_IDENTITY_DUPLICATE_OR_INVALID")
        seen.add(key)
        league_counts[league]+=1
        if key in pilot:
            known=pilot[key]
            if (row["league"]!=known["league"] or
                row["official_news_url"]!=known["source_url"] or
                row["native_team_id"]!=known["native_team_id"] or
                row["status"]!="PILOT_INDEX_OBSERVED_PLAYER_UNVERIFIED"):
                raise ValueError("PILOT_SITE_IDENTITY_MISMATCH_OR_PROMOTED")
            observed_counts[league]+=1
        else:
            if (row["official_news_url"] is not None or
                row["native_team_id"] is not None or
                row["status"]!="OFFICIAL_NEWS_URL_NOT_VERIFIED"):
                raise ValueError("UNVERIFIED_CLUB_MUST_NOT_BE_CONNECTED")
        if (row["membership_evidence_url"]!=doc["evidence_urls"].get(league)):
            raise ValueError("OFFICIAL_LEAGUE_MEMBERSHIP_URL_MISMATCH")
    if set(pilot)!=set(seen)&set(pilot) or league_counts!=COUNTS or (
            observed_counts!={k:2 for k in COUNTS}):
        raise ValueError("CLUB_COVERAGE_COUNTS_OR_PILOT_SCOPE_CONFLICT")
    # 2026/27 EuroLeague and EuroCup may have different teams from prior
    # seasons. Guard known changes and Rome's two distinct clubs.
    league_by_name={(x["league"],x["team_name"]) for x in teams}
    needed={
        ("EUROLEAGUE","Besiktas Istanbul"),
        ("EUROCUP","Bosna BH Telecom Sarajevo"),
        ("EUROCUP","Maxima Roma"),
        ("EUROCUP","Roma Basketball"),
    }
    if not needed<=league_by_name or (
        "AS Monaco" in [x["team_name"] for x in teams
                        if x["league"]=="EUROCUP"]):
        raise ValueError("2026_27_LEAGUE_MEMBERSHIP_REVISION_MISSING")
    return doc


def summary():
    data=load_coverage()
    return dict(
        format="OFFICIAL_CLUB_COVERAGE_AUDIT_V1",
        season=data["season"],
        league_totals=COUNTS,
        members_total=len(data["teams"]),
        pilot_source_pages_observed=6,
        source_pages_not_yet_verified=76,
        league_observed={k:sum(
            x["league"]==k and x["official_news_url"] is not None
            for x in data["teams"]) for k in COUNTS},
        league_source_pending={k:sum(
            x["league"]==k and x["official_news_url"] is None
            for x in data["teams"]) for k in COUNTS},
        all_clubs_official_news_connected=False,
        roster_identity_verified=False,
        injury_status_comprehensively_verified=False,
        model_input=False,production_changed=False,requests=0)


def run(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary",action="store_true")
    args=parser.parse_args(argv)
    print(json.dumps(summary(),ensure_ascii=False,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(run())
