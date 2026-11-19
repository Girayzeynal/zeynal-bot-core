"""Current command aliases bound to verified European club identities.

This adapter does not edit native participant snapshots, historical clocks,
prepared models or forecasts. No fuzzy matching or inference of membership.
"""
from datetime import datetime
import time
from zoneinfo import ZoneInfo

from core.league_identity import normalize_name, resolve_league
from core.team_identity import IdentityRefusal, TeamIdentityRegistry
from providers.season_participants import _variants
from hybrid_engine.europe_prematch import AutomaticEuropeanService

VERSION = 'EUROPE_COMMAND_ALIASES_V1'
# League + provider code + exact native name anchor, not a code-only mapping.
RULES = (
    ('EUROCUP', 'TRT', 'Baglietto Derthona Tortona', ('Derthona Basket',)),
    ('EUROCUP', 'RIG', 'Riga Zelli', ('Rigas Zelli',)),
    ('EUROCUP', 'FRA', 'Skyliners Frankfurt', ('Frankfurt Skyliners',)),
    ('EUROCUP', 'VNC', 'Umana Reyer Venice', ('Reyer Venezia',)),
    ('EUROCUP', 'NAP', 'Napoli Basketball', ('Napoli Basket',)),
)


def additions(league, code, native_names):
    names = {normalize_name(n) for n in native_names}
    return {normalize_name(alias) for scope, pid, anchor, aliases in RULES
            if scope == league and pid == code and normalize_name(anchor) in names
            for alias in aliases}


class EuropeanCommandRegistry(TeamIdentityRegistry):
    """Resolve current commands without backdating newly introduced aliases."""
    def __init__(self):
        super().__init__()
        self.aliases_available_at_utc = int(time.time())

    def resolve(self, league, season, name, *, asof_utc):
        if type(asof_utc) is not int or not 0 < asof_utc <= int(time.time()):
            raise IdentityRefusal('INVALID_IDENTITY_CUTOFF')
        code = resolve_league(league).code
        key = normalize_name(name)
        candidates = []
        members = ()
        if code in ('EUROLEAGUE', 'EUROCUP') and asof_utc >= self.aliases_available_at_utc:
            members = self.participants(code, season, asof_utc=asof_utc)
            for team in members:
                native = [team.official_name] + [a for a, _, _, start, end in team.aliases
                    if start <= asof_utc and (end is None or asof_utc < end)]
                if any(provider == 'EUROLEAGUE_LIVE' and key in additions(code, pid, native)
                       for provider, pid in team.provider_ids):
                    candidates.append(team)
        if not candidates:
            return super().resolve(code, season, name, asof_utc=asof_utc)
        # Include every native collision without recording a false refusal for
        # a successfully resolved curated command.
        candidates.extend(team for team in members if any(
            start <= asof_utc and (end is None or asof_utc < end) and normalize_name(alias) == key
            for alias, _, _, start, end in team.aliases))
        found = {t.internal_id: t for t in candidates}
        if len(found) != 1:
            return self._refuse('AMBIGUOUS_TEAM_ALIAS', code, season, key, tuple(found), asof_utc)
        return next(iter(found.values()))


class EuropeanCommandService(AutomaticEuropeanService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.preflight.registry = EuropeanCommandRegistry()

    def existing(self, day, home, away):
        """Current alias lookup against original, SHA-verified archive sources.

        The alias is used now, never asserted to have been known at forecast
        time. No provider request, model run or original-record modification.
        """
        h, a = normalize_name(home), normalize_name(away)
        found = []
        for item in self.registry.independent_records():
            p = item['payload']; g = p['fixture']
            if datetime.fromtimestamp(g['start_ts_utc'], ZoneInfo('Europe/Istanbul')).date().isoformat() != day:
                continue
            self.pair(p)  # validates original source, league and fixture identity
            receipt = self.registry.read_asset(p['fixture_source'])
            rows = receipt['document']['data']
            targets = [r for r in rows if r['identifier'] in g['provider_fixture_ids']]
            if len(targets) != 1:
                continue
            all_keys = {}
            for row in rows:
                for side in ('local', 'road'):
                    club = row[side]['club']; pid = club['code']
                    native = [v['name'] for v in _variants(club, p['source_available_max_utc'], include_city=True)]
                    keys = {normalize_name(n) for n in native}
                    keys.update(additions(self.league, pid, native))
                    all_keys.setdefault(pid, set()).update(keys)
            ids = [targets[0][side]['club']['code'] for side in ('local', 'road')]
            # A native or curated alias shared by any archived club is refused.
            hits = [{pid for pid, keys in all_keys.items() if key in keys} for key in (h, a)]
            if hits == [{ids[0]}, {ids[1]}]:
                found.append(item)
            elif ids[0] in hits[0] and ids[1] in hits[1]:
                raise IdentityRefusal('AMBIGUOUS_TEAM_ALIAS')
        if len(found) > 1:
            raise IdentityRefusal('EUROPE_AMBIGUOUS_ARCHIVED_PAIR')
        return found[0] if found else None

    async def analyze(self, league, day, home, away):
        # The inherited busy-lock replay path precedes its normal league check.
        if resolve_league(league).code != self.league:
            raise IdentityRefusal('EUROPE_SERVICE_LEAGUE_MISMATCH')
        try:
            return await super().analyze(league, day, home, away)
        except IdentityRefusal as exc:
            return dict(status='ABSTAIN', reason=str(exc),
                html='Takım adı tekil olarak doğrulanamadı; /euroleague veya /eurocup listesindeki tam komutu kullanın. '
                     'Tahmin üretilmedi; kayıtlı tahminler korunuyor.')
