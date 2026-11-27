"""Read-only source inventory: configuration is not connectivity or model use."""
import json
import os

from hybrid_engine.provider_access import ProviderAccess, credentials
from hybrid_engine.official_all_82_club_batch import batch_probe
from hybrid_engine.three_league_roster_bridge import readiness
from hybrid_engine.europe_injury_public_sources import SITE_URLS


def inventory():
    try:
        api=ProviderAccess(credentials()).configuration()
        config_status='LOCAL_CONFIGURATION_READ'
    except (ValueError,OSError):
        api={}
        config_status='LOCAL_CONFIGURATION_INVALID_NO_VALUES_EXPOSED'
    clubs=batch_probe(live=False)
    return dict(status='SOURCE_INVENTORY_ONLY_NOT_LIVE_TEST',
        api_configuration_status=config_status, api_configuration=api,
        sportsdataio_legacy_env_present=bool(os.environ.get('SPORTSDATA_API_KEY','').strip()),
        sportsdataio_legacy_status='ADAPTER_EXISTS_NATIVE_PIPELINE_USE_NOT_ATTESTED',
        native_sources=['ESPN','NBA_OFFICIAL_PDF','EUROPE_OFFICIAL_SEASON_REGISTRATION'],
        european_editorial_sources=[name for name,url in SITE_URLS],
        club_registry_size=clubs['registry_size'], club_league_counts=clubs['league_counts'],
        clubs_live_checked_in_this_report=0,
        club_player_injury_feeds_verified_in_this_report=0,
        prior_roster_wiring=readiness(),
        network_requests=0, production_changed=False, player_effect_applied=False)


if __name__=='__main__':
    print(json.dumps(inventory(),ensure_ascii=False,indent=2))
