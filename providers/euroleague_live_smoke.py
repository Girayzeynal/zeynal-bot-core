"""Read-only source audit and sampled box-score reconciliation for E/U seasons."""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
import time

from league_profiles import get_league_profile
from providers.euroleague_live import BASE, EuroleagueLiveAdapter, identity, replay_pace_evidence


async def check_sources(leagues, year, samples=2):
    if type(samples) is not int or not 1 <= samples <= 6:
        raise ValueError("Sample count must be between one and six")
    adapter = EuroleagueLiveAdapter()
    results = []
    try:
        for league in leagues:
            canonical, code, _, season = identity(league, year)
            catalog = await adapter.fetch_catalog(canonical, year)
            completed = [g for g in catalog["games"] if g["status"] == "PLAYED"]
            recent = sorted(completed, key=lambda g: g["start_ts_utc"], reverse=True)
            selected = recent[:1]
            overtime = next((g for g in recent if g["duration_minutes"] > 40 and g not in selected), None)
            if overtime is not None and samples > 1:
                selected.append(overtime)
            selected += [g for g in recent if g not in selected][:samples-len(selected)]
            estimates, unavailable = [], []
            for game in selected:
                evidence = await adapter.fetch_pace_evidence(catalog["raw_games"][game["provider_fixture_id"]],
                                                              league=canonical, year=year)
                if evidence is None:
                    unavailable.append(game["provider_fixture_id"])
                else:
                    replay_pace_evidence(evidence)
                    estimates.append(evidence)
            try:
                get_league_profile(canonical)
            except ValueError:
                profile = "UNREGISTERED"
            else:
                profile = "REGISTERED_NOT_EMPIRICALLY_VALIDATED"
            facts = json.dumps(catalog["games"], sort_keys=True, separators=(",", ":"), allow_nan=False)
            results.append(dict(league=canonical, season_code=season,
                source_url=f"{BASE}/{code}/seasons/{season}/games",
                catalog_sha256=hashlib.sha256(facts.encode()).hexdigest(),
                quality={k: v for k, v in catalog.items() if k not in ("games", "raw_games", "league")},
                played_games=len(completed), unplayed_games=len(catalog["games"])-len(completed),
                historical_phase_counts=dict(Counter(g["phase"] for g in completed)),
                sampled_boxscores=len(selected), reconciled_estimates=len(estimates),
                unavailable_fixture_ids=unavailable, estimates=estimates,
                analysis_profile=profile, production_ready=False, analysis_adapter_registered=False))
        passed = bool(results) and all(r["sampled_boxscores"] == samples and not r["unavailable_fixture_ids"]
            and r["quality"]["invalid_records"] == 0 and not r["quality"]["conflicting_fixture_ids"] for r in results)
        return dict(status="pass" if passed else "incomplete", observed_at_utc=int(time.time()),
                    verification_scope="single_provider_internal_consistency", results=results)
    finally:
        await adapter.aclose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--leagues", nargs="+", choices=("EUROLEAGUE", "EUROCUP"), default=["EUROLEAGUE", "EUROCUP"])
    parser.add_argument("--samples", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(check_sources(args.leagues, args.year, args.samples))
    except (ValueError, RuntimeError, OSError):
        print(json.dumps({"status": "source_audit_failed"}))
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
