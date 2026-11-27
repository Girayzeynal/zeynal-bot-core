"""Exact public-news player identity audit; never availability or score input."""
from core.league_identity import normalize_name
from hybrid_engine.europe_injury_public_sources import _official_team_key

def keys(name):
    if not isinstance(name,str) or not name.strip():return set()
    try:
        out={normalize_name(name)}
        if name.count(',')==1:
            a,b=name.split(',')
            if a.strip() and b.strip():out.add(normalize_name(b+' '+a))
        return out
    except ValueError:return set()

def match_candidates(ctx,native,news):
    result=dict(fixture_id=ctx.get('fixture_id'),status='IDENTITY_ONLY',
        matched=[],unmatched=0,ambiguous=0,conflicts=0,
        availability_verified=False,minutes_verified=False,model_input=False)
    if not native or not news or native.get('fixture_id')!=ctx.get('fixture_id'):
        result['status']='SOURCE_DIRECTORY_OR_NEWS_MISSING';return result
    league=ctx['league'];teams={}
    for side in ('home','away'):
        row=native.get('teams',{}).get(side,{})
        key=_official_team_key(league,ctx[side]['official_name'])
        if key and row.get('status')=='OFFICIAL_SEASON_REGISTRATION_OBSERVED':
            teams[key]=(side,row.get('registered_players',[]))
    found={}
    for source in news.get('sources',[])[:5]:
        for hint in source.get('unverified_player_candidates',[])[:96]:
            team=teams.get(_official_team_key(league,hint.get('team_text')))
            if not team:continue
            side,players=team
            names=keys(hint.get('player_text'))
            candidates=[p for p in players if p.get('player_id') and names & keys(p.get('name'))
                        and str(p.get('team_id'))==str(ctx[side]['provider_id'])]
            if len(candidates)!=1:
                result['ambiguous' if candidates else 'unmatched']+=1;continue
            p=candidates[0];k=(side,p['player_id'])
            entry=found.setdefault(k,dict(side=side,player_id=p['player_id'],name=p['name'],observations=[]))
            obs=dict(source=source['source'],status=hint['source_reported_status'])
            if obs not in entry['observations']:entry['observations'].append(obs)
    for row in found.values():
        row['conflicting_statuses']=len({v['status'] for v in row['observations']})>1
        result['conflicts']+=int(row['conflicting_statuses'])
        result['matched'].append(row)
    return result

def render_matches(report):
    lines=['OYUNCU HABERİ / RESMÎ KİMLİK EŞLEŞTİRMESİ (KATILIM KANITI DEĞİL)',
           'Eşleşen: '+str(len(report['matched']))+' · Belirsiz: '+str(report['ambiguous'])+
           ' · Eşleşmeyen: '+str(report['unmatched'])+' · Çelişkili: '+str(report['conflicts'])]
    for row in report['matched']:
        lines.append(row['name']+' · '+row['player_id']+' · '+', '.join(
            o['source']+': '+o['status'] for o in row['observations']))
    lines.append('Yayın zamanı, maç katılımı ve dakika doğrulanmadı; skor girdisi değildir.')
    return '\n'.join(lines)
