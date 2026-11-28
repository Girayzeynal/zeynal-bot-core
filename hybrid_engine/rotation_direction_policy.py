"""Direction-first policy: no numeric residual can authorize a change."""
from collections import Counter
from hybrid_engine.rotation_report import actual_periods

POLICY='DIRECTION_FIRST_V1'
BLOCK='NO_EXACT_ROTATION_CONTRACT_DIRECTION_EVIDENCE'

def action(outcome,*,verified=False):
    # Only independently replayed contract settlements may be verified.
    # A loss authorizes investigation, not parameter mutation.
    if verified is not True:return 'HOLD_UNVERIFIED'
    return {'WIN':'PROTECT_SUCCESS','LOSS':'INVESTIGATE_FAILURE','PUSH':'HOLD_PUSH',
        'PENDING_FINAL':'HOLD_PENDING'}.get(outcome,'HOLD_UNVERIFIED')

def blocked():
    return dict(status='HOLD_UNVERIFIED',reason=BLOCK,policy=POLICY,
        parameter_change=False,new_candidate=False)

def audit(entries,now):
    # Rotation has no exact-model pregame contract decision adapter yet.
    # V1/V3 quotes or score residuals cannot be substituted.
    counts=Counter()
    for _,_,_,p,row in entries:
        if actual_periods(row,now) is None:counts['pending']+=1
        else:counts['settled_unverified_direction']+=1
    return dict(policy=POLICY,settled=counts['settled_unverified_direction'],
        pending=counts['pending'],verified_wins=0,verified_losses=0,
        verified_pushes=0,investigate=0,parameter_change=False,reason=BLOCK)

def render(entries,now,*,folder=None,ledger=None):
    r=audit(entries,now)
    lines=['NBA ROTASYON — YÖN ÖNCELİKLİ ÖĞRENME',
        'Başarılı yön korunur; başarısız yön incelemeye alınır. Sayısal fark tek başına müdahale nedeni değildir.',
        f"Sonuçlanan maç: {r['settled']} | Bekleyen: {r['pending']}"]
    if folder is not None:
        from hybrid_engine.rotation_direction_evidence import audit as evidence_audit
        evidence=evidence_audit(folder,entries,now,ledger=ledger)
        c=evidence['counts']
        lines.extend([f"Kaynağı yeniden doğrulanan maç: {evidence['fixtures']} | Barem gözlemi: {evidence['observations']}",
            f"Doğrulanmış yön gözlemi: başarılı {c.get('WIN',0)} | başarısız {c.get('LOSS',0)} | iade {c.get('PUSH',0)} | bekleyen {c.get('PENDING_FINAL',0)}",
            'Gözlem sayısı maç başarı oranı değildir; farklı baremler ayrı gözlemlerdir.'])
        for k,n in sorted(c.items()):
            if k not in ('WIN','LOSS','PUSH','PENDING_FINAL'):lines.append(f'{k}: {n}')
        for k,n in sorted(evidence['excluded'].items()):lines.append(f'Dışlanan: {k} ({n})')
        for f in evidence['failures'][:30]:
            lines.append(f"İNCELE: {f['home']} – {f['away']} | {f['period']} {f['market']} | {f['bookmaker_id']} {f['line']} | model {f['point_mean']:.2f} | gerçek {f['actual']} | kök neden henüz kanıtlanmadı.")
        if not any(c.get(k,0) for k in ('WIN','LOSS','PUSH','PENDING_FINAL')):lines.append('HOLD_UNVERIFIED — uygun doğrulanmış normal süre karar kaydı yok.')
    else:
        lines.extend(['Doğrulanmış başarılı yön: 0 | Başarısız yön: 0 | İade: 0',
            f"Yönü belirsiz sonuçlanan maç: {r['settled']}",
            'HOLD_UNVERIFIED — rotasyon kaydına bağlı doğrulanmış maç öncesi karar ve ödeme kuralı yok.'])
    lines.extend(['V1/V3 fiyatları tek başına rotasyonun kanıtı değildir.',
        'Yeni katsayı veya ortak sayı düzeltmesi uygulanmadı. Başarısız yön bile otomatik değişiklik yetkisi vermez.'])
    from hybrid_engine.elite_render import split_blocks
    return split_blocks(lines,limit=3200)
