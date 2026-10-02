"""Explicit retained clause assessments over the shared settlement engine.

This bounded vocabulary establishes individual dimensions only. Missing branches
remain unknown; equal numeric windows do not equate begins/rescheduling semantics.
"""
from hashlib import sha256
from app.settlement import profile,fact,compare_profiles


def retained_terms(sources):
    profiles={}
    for venue,s in sources.items():
        native=s['metadata']
        text='\n\n'.join(native.get(k,'') for k in (('rules_primary','rules_secondary') if venue=='kalshi' else ('description',))).strip()
        if not text:continue
        digest=sha256(text.encode()).hexdigest();dimensions={};payouts={}
        if venue=='kalshi' and any(clause in text for clause in ('begins within 48 hours of its originally scheduled start time','begins within 48 hours from its originally scheduled start time')) and 'not started within 48 hours' in text and 'fair price' in text:
            postpone='begins within 48 hours of original start; otherwise venue fair price'
        elif venue=='polymarket_us' and 'rescheduled to a date within two days' in text and 'last fair market price' in text:
            postpone='rescheduled date within two days; otherwise last fair market price'
        elif venue=='polymarket_us' and 'rescheduled to a date within two weeks' in text and 'last fair market price' in text:
            postpone='rescheduled date within two weeks; otherwise last fair market price'
        elif venue=='polymarket_us' and 'rescheduled to start within two calendar days of the originally scheduled date and time' in text and 'last fair market price' in text:
            postpone='rescheduled start within two calendar days of original date/time; otherwise last fair market price'
        else:postpone=None
        if postpone:
            dimensions['postponement']=fact(postpone,evidence=digest)
            payouts['postponed_outside_window']=dict(kind='discretionary',evidence=digest,reason='Independent venue fair-value determination')
        if '$0.50' in text and ('tie' in text.lower() or 'tied' in text.lower()):
            dimensions['tie']=fact('fraction-0.50',evidence=digest);payouts['tie']=dict(kind='fraction',value='0.5',evidence=digest)
        source=dict(url=s['provenance'][0]['path'],sha256=digest,text=text,receipt_evidence=s['provenance'])
        profiles[venue]=profile(sources=[source],dimensions=dimensions,payouts=payouts,actor='Codex bounded retained-clause assessment')
    if set(profiles)!=set(sources):return None
    result=compare_profiles(profiles['kalshi'],profiles['polymarket_us'])
    result.update(qualified=False,evidence=[p['sources'] for p in profiles.values()],profiles_detail=profiles)
    if result['status'] in ('EXACT','COMPATIBLE'):result['status']='SUPPORTED'
    return result
