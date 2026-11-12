"""Explicit competition identities and provider capabilities, never team lists."""
from dataclasses import dataclass
from pathlib import Path
import json
import unicodedata


def normalize_name(value):
    if type(value) is not str or not value.strip() or len(value)>300:
        raise ValueError('NONEMPTY_BOUNDED_NAME_REQUIRED')
    value=value.replace('ı','i').replace('İ','I')
    value=''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))
    result=''.join(c for c in value if c.isalnum())
    if not result: raise ValueError('NONEMPTY_NORMALIZED_NAME_REQUIRED')
    return result


@dataclass(frozen=True)
class LeagueIdentity:
    code: str
    aliases: tuple
    provider: str | None = None
    competition_code: str | None = None

    @property
    def identity_namespace(self):
        # EuroLeague's club codes span E/U competitions; ESPN numeric IDs are
        # sport/league scoped and must not collide with another competition.
        return 'EUROLEAGUE_LIVE:CLUB' if self.provider=='EUROLEAGUE_LIVE' else str(self.provider)+':'+self.code


_SPECS=(
    LeagueIdentity('NBA',('NBA',),'ESPN'),
    LeagueIdentity('EUROLEAGUE',('EuroLeague','EL','Euro League'),'EUROLEAGUE_LIVE','E'),
    LeagueIdentity('EUROCUP',('EuroCup','ULEB EuroCup'),'EUROLEAGUE_LIVE','U'),
    LeagueIdentity('FIBA_EUROCUP',('FIBA EuroCup','FIBA Europe Cup')),
    LeagueIdentity('BCL',('BCL','Basketball Champions League')),
    LeagueIdentity('ACB',('ACB','Spain ACB','Liga ACB')),
    LeagueIdentity('LBA',('LBA','Italy Serie A','Italy LBA','LEGA','Serie A')),
    LeagueIdentity('BSL',('BSL','Turkey BSL','Türkiye BSL','TBL')),
    LeagueIdentity('GBL',('GBL','Greece A1','Greece Basket League','Greek Basket League')),
    LeagueIdentity('BBL',('BBL','Germany BBL')),
    LeagueIdentity('LNB',('LNB','France Pro A','France LNB','LNB Elite')),
    LeagueIdentity('NBL',('NBL','Australia NBL')),
    LeagueIdentity('CBA',('CBA','China CBA')),
    LeagueIdentity('KBL',('KBL','Korea KBL')),
    LeagueIdentity('SBL',('SBL','Sweden SBL')),
)


def league_catalog():
    result={s.code:s for s in _SPECS}
    # Preserve newly configured competitions, but never guess a provider for them.
    configured=json.loads(Path(__file__).resolve().parents[1].joinpath('leagues.json').read_text())
    for row in configured:
        name=row['name']
        if not any(normalize_name(name) in {normalize_name(a) for a in (s.code,*s.aliases)} for s in result.values()):
            code='CONFIGURED_'+normalize_name(name).upper()
            result[code]=LeagueIdentity(code,(name,))
    return result


def resolve_league(value):
    key=normalize_name(value)
    found=[s for s in league_catalog().values() if key in {normalize_name(a) for a in (s.code,*s.aliases)}]
    if len(found)!=1: raise ValueError('UNKNOWN_OR_AMBIGUOUS_LEAGUE')
    return found[0]
