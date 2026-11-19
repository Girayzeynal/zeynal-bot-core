"""Core-result consensus for a NEW read-only research view.

Do not replace historical_research.py or change existing V1/V2 study pins.
Supplemental statistics remain source-versioned at their original clocks.
"""
from collections import defaultdict
from copy import deepcopy

from core.team_identity import digest
from historical_research import historical_rows

VERSION='SOURCE_VERSIONED_CORE_RESULT_CONSENSUS_V1'
CORE=('record_type','league','season','fixture_id','fixture_start_utc','provider',
      'home_team_id','away_team_id','final_scores','periods')


def union(catalog_pins):
    groups=defaultdict(dict);cores={};aliases={};slots={}
    for catalog,pin in catalog_pins:
        # Existing native decoder validates every individual receipt/catalog.
        for versions in historical_rows([(catalog,pin)]):
            for original in versions:
                row=deepcopy(original);key=(row['league'],row['fixture_id'])
                core={k:row[k] for k in CORE}
                if key in cores and cores[key]!=core:raise ValueError('RESEARCH_CORE_RESULT_CONFLICT')
                cores[key]=core
                for pid in row['provider_fixture_ids']:
                    alias=(row['provider'],row['league'],pid)
                    if alias in aliases and aliases[alias]!=key:raise ValueError('RESEARCH_PROVIDER_ID_CONFLICT')
                    aliases[alias]=key
                for team in (row['home_team_id'],row['away_team_id']):
                    slot=(row['league'],row['season'],team,row['fixture_start_utc'])
                    if slot in slots and slots[slot]!=key:raise ValueError('RESEARCH_TEAM_START_CONFLICT')
                    slots[slot]=key
                groups[key][digest(row)]=row
    return [sorted(v.values(),key=lambda r:(r['ingested_at_utc'],r['observed_at_utc'],r['source_catalog_sha256']))
            for key,v in sorted(groups.items(),key=lambda kv:(cores[kv[0]]['fixture_start_utc'],kv[0]))]
