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

def render(entries,now):
    r=audit(entries,now)
    return ['NBA ROTASYON — YÖN ÖNCELİKLİ ÖĞRENME\n'
        'Başarılı yön korunur; başarısız yön kök neden incelemesine alınır.\n'
        'Sayısal fark tek başına müdahale nedeni değildir.\n'
        f"Sonuçlanan maç: {r['settled']} | Bekleyen: {r['pending']}\n"
        'Doğrulanmış başarılı yön: 0 | Başarısız yön: 0 | İade: 0\n'
        f"Yönü belirsiz sonuçlanan maç: {r['settled']}\n"
        'HOLD_UNVERIFIED — rotasyon kaydına bağlı doğrulanmış maç öncesi karar ve ödeme kuralı yok.\n'
        'V1/V3 fiyatları rotasyonun kanıtı değildir. Yeni katsayı veya ortak sayı düzeltmesi uygulanmadı.\n'
        'Başarısız yön incelemesi bile otomatik katsayı değişikliği yetkisi vermez.']
