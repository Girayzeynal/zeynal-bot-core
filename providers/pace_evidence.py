"""Dispatch source-specific evidence checks without mixing competitions or seasons."""
import math
import time

from providers.espn_pace_evidence import validate_pace_evidence as validate_espn
from providers.espn_pace_evidence import same_pace_observation
from providers.euroleague_live import PACE_METHOD, identity, replay_pace_evidence


def validate_pace_evidence(record, *, league, team=None, prediction_utc=None):
    if getattr(record, "source", None) != PACE_METHOD:
        return validate_espn(record, league=league, prediction_utc=prediction_utc)
    try:
        evidence = record.pace_evidence
        game = replay_pace_evidence(evidence)
        canonical, _, _, season = identity(league, evidence["snapshot"]["year"])
        side, opponent = ("home", "away") if record.home else ("away", "home")
        if (game["league"] != canonical or game["season_code"] != season or game["phase"] != "RS"
                or type(record.home) is not bool or record.timestamp_precision != "exact"
                or not isinstance(team, str) or team.strip().upper() != game[f"{side}_team_id"]
                or record.game_id != game["provider_fixture_id"] or record.ts_utc != game["start_ts_utc"]
                or record.pts_for != game[f"actual_{side}"] or record.pts_against != game[f"actual_{opponent}"]):
            raise ValueError("Euroleague Live record league/season/team/score binding mismatch")
        observed = evidence["snapshot"]["observed_at_utc"]
        if type(observed) is not int or not record.ts_utc < observed <= int(time.time()):
            raise ValueError("Invalid Euroleague Live observation time")
        if prediction_utc is not None and (type(prediction_utc) is not int or not observed < prediction_utc):
            raise ValueError("Euroleague Live observation was unavailable before prediction")
        if (type(record.pace) not in (int, float) or not math.isfinite(record.pace)
                or abs(record.pace - evidence["pace"]) > 1e-9):
            raise ValueError("Euroleague Live pace differs from replayed evidence")
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Invalid Euroleague Live record evidence") from exc


def validate_series_scope(records):
    """Euroleague Live series must use one season and this evidence-backed source."""
    euro = [row for row in records if getattr(row, "source", None) == PACE_METHOD]
    if not euro:
        return
    try:
        seasons = {row.pace_evidence["game"]["season_code"] for row in euro}
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Missing source-specific series scope") from exc
    if len(euro) != len(records) or len(seasons) != 1:
        raise ValueError("Mixed season/provider series requires an explicit separate store")


def pace_available_before(record, *, league, prediction_utc, team=None):
    try:
        validate_pace_evidence(record, league=league, team=team, prediction_utc=prediction_utc)
        return True
    except ValueError:
        return False
