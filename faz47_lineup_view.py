"""Read-only development view of FAZ46 evidence; never a prediction or write.

The source/PIT authority stays in prematch_context. No FAZ39 module is imported,
no projected five is inferred, and unknown injury/availability stays unknown.
"""
from copy import deepcopy

from prediction_inputs import digest
from faz40_archive import require
from faz41_evidence import REGISTRY, REGISTRY_PIN
from faz41_faz40 import prematch_context
from faz42_snapshot import validate_model


FORMAT = 'FAZ47_READ_ONLY_LINEUP_VIEW_V1'


def lineup_view(observations, *, fixture, cutoff_utc, model_manifest,
                trusted_model_sha256, maximum_age_seconds=3600,
                registry=REGISTRY, registry_pin=REGISTRY_PIN):
    """Replay source evidence before exposing any lineup status.

    The model is a pinned reference, not an assertion of execution. Historical
    replay is allowed; this function cannot create a prospective prediction.
    Rejected evidence raises ValueError rather than yielding a partial view.
    """
    try:
        observations, fixture, model_manifest, registry = deepcopy(
            (observations, fixture, model_manifest, registry))
        require(model_manifest['sha256'] == trusted_model_sha256,
                'TRUSTED_LINEUP_MODEL_PIN_MISMATCH')
        model = validate_model(model_manifest, cutoff_utc)
        require(type(maximum_age_seconds) is int and maximum_age_seconds > 0,
                'INVALID_LINEUP_EVIDENCE_MAXIMUM_AGE')
        context = prematch_context(
            observations, fixture=fixture, cutoff_utc=cutoff_utc,
            maximum_age_seconds=maximum_age_seconds,
            registry=registry, registry_pin=registry_pin)
        p = context['payload']
        require(all(o['payload']['data_type'] in ('OFFICIAL_LINEUP', 'ROSTER')
                    for o in observations), 'LINEUP_OBSERVATIONS_REQUIRED')
        if p['usage'] != 'NO_EVIDENCE':
            require((p['usage'] == 'SYNTHETIC_TEST') ==
                    (model['purpose'] == 'SYNTHETIC_TEST'),
                    'LINEUP_MODEL_EVIDENCE_USAGE_MISMATCH')
        sources = {}
        for o in observations:
            source = o['payload']
            sources[o['sha256']] = dict(
                evidence_sha256=o['sha256'], raw_sha256=source['raw_sha256'],
                provider=source['provider'], provider_fixture_id=source['provider_fixture_id'],
                team_id=source['claims']['team_id'], data_type=source['data_type'],
                source_url=source['source_url'], published_at_utc=source['published_at_utc'],
                observed_at_utc=source['observed_at_utc'], ingested_at_utc=source['ingested_at_utc'],
                materialized_at_utc=source['materialized_at_utc'])
        teams = {}
        listings = p.get('unconfirmed_source_rosters', {})
        for side in ('home', 'away'):
            team = fixture[side + '_team_id']
            roster = p['rosters'].get(team)
            listing = listings.get(team)
            official = roster is not None
            teams[side] = dict(
                team_id=team, status='OFFICIAL' if official else 'UNAVAILABLE',
                reason='REPLAYED_PERMITTED_ANNOUNCEMENT' if official else
                       'ABSTAIN_SOURCE_LISTING_IS_NOT_STARTING_FIVE' if listing else
                       'ABSTAIN_NO_CONFIRMED_LINEUP',
                starting_five=deepcopy(roster['payload']['starting_five']) if official else None,
                confirmed_source_roster=deepcopy(roster['payload']['players']) if official else None,
                unconfirmed_source_roster=deepcopy(listing),
                excluded=None, uncertain=None, active_for_target=None,
                availability_status='NOT_ESTABLISHED',
                evidence_sha256=sorted(k for k, v in sources.items() if v['team_id'] == team))
        payload = dict(
            schema_version=1, format=FORMAT, purpose='READ_ONLY_DEVELOPMENT_NOT_PREDICTION',
            fixture=fixture, cutoff_utc=cutoff_utc, maximum_age_seconds=maximum_age_seconds,
            evidence_usage=p['usage'], model_manifest=model_manifest,
            model_sha=model['git_sha'], trusted_model_sha256=trusted_model_sha256,
            model_binding='PINNED_REFERENCE_NOT_EXECUTION_ATTESTATION',
            registry_sha256=registry_pin, context_sha256=context['sha256'],
            evidence_sha256=sorted(sources), sources=[sources[k] for k in sorted(sources)],
            source_digest=digest(dict(context=context['sha256'], evidence=sorted(sources), registry=registry_pin)),
            teams=teams, missing=deepcopy(p['missing']),
            projected_adapter_status='NOT_AVAILABLE',
            source_attestation=p['source_attestation'],
            production_coefficients_changed=False, prospective_records_created=0,
            storage_status='NOT_ACTIVATED')
        return dict(payload=payload, sha256=digest(payload))
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError('MALFORMED_LINEUP_VIEW_INPUT') from exc


def validate_lineup_view(view, observations, **expected):
    """Rebuild with the caller's expected fixture/cutoff/model and source pins.

    Rehashing a changed status, source reference or model claim cannot replace
    replay. The returned object is independent of the supplied view and inputs.
    """
    rebuilt = lineup_view(observations, **expected)
    try:
        require(type(view) is dict and set(view) == {'payload', 'sha256'} and
                digest(view['payload']) == view['sha256'] and view == rebuilt,
                'LINEUP_VIEW_CANNOT_REPLAY')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('LINEUP_VIEW_CANNOT_REPLAY') from exc
    return rebuilt
