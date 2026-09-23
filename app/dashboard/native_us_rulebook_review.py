"""Review7: explicit US hierarchy, without inventing historical effective coverage."""
from pathlib import Path
import hashlib,json
VERSION='atl-gb-native-review-7'
ROOT=Path(__file__).resolve().parents[2]
SOURCES={
 'settlement':('evidence/b6-precedence-final-20260923/acquisition/02-response.bin','731230ebe68ce71051c4256e772a79099f5f6005d640723aab95b116eab79af0'),
 'regulatory':('evidence/b6-precedence-followup-20260923/acquisition/01-response.bin','957a87b8a72debc6dfbfee26277c5870090cfcfcabd8a495ac3add95c69c0257'),
 'rulebook':('evidence/b6-us-rulebook-dated-20260923/acquisition/01-response.bin','e7b7793e75dd61a8adaf807c588e1212cf0600100e5727d7d546ba0a0b7f35e5')}

def conditional_priority(rows,*,market_id,applicability_established=False):
    """Rule1.5 priority for a supported topic; never equate hierarchy with applicability."""
    out=dict(available=False,selected=None,reason='Exact contract effective applicability is not established')
    if applicability_established is not True or not rows:return out
    rank={'rulebook':0,'product_specifications':1,'contract_terms':2}
    if any(r.get('market_id')!=market_id or r.get('layer') not in rank or not isinstance(r.get('value'),str) or not r['value'] for r in rows):return dict(out,reason='Missing/unsupported scoped rule')
    best=max(rank[r['layer']] for r in rows);top=[r for r in rows if rank[r['layer']]==best]
    if len({r['value'] for r in top})!=1:return dict(out,reason='Conflict within same priority requires authoritative clarification')
    return dict(available=True,selected=top[0],reason='Conditional Rule1.5 hierarchy only; does not qualify fee, payout or comparison')

def facts():
    for path,expected in SOURCES.values():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=expected:raise ValueError('US rulebook evidence mismatch')
    return dict(sources={k:dict(file=p,sha256=h) for k,(p,h) in SOURCES.items()},
        rulebook_url='https://polymarketexchange.com/files/legal/Polymarket%20US%20Rulebook%20(2026.09.14).pdf',
        document_date='2026-09-14',effective_at_historical_cutoff=None,
        priority=dict(rule='1.5',order=['contract_terms','product_specifications','rulebook'],established_document_text=True,historical_applicability=False),
        alternative_settlement='Acquired guide expressly follows market Settlement Description; generic50-50 examples do not replace779756 last-fair-price terms',
        fees=dict(rule='3.8',authority='Exchange sets fees and may post updated schedules; transaction rates, bank/account costs and agreed charges are distinct',settlement_charge=None),
        amendments=dict(rule='1.4',effective='Date determined by company after required filing/approval, not inferred solely from cover date'),
        notices=dict(rule='3.10(e)',limitation='Failure to publish notice does not affect effectiveness; public search silence cannot prove no change'),
        exceptions=dict(rules=['10.3','10.4'],modifications='Company may modify specifications including settlement date/payout condition and notify',review='Discretionary outcome review; obvious-error reversal; determinations final'),
        units='Rule10.1 permits fractional units generally; this is not proof of API/market779756 support and does not change the retained whole-contract calculations',
        remaining=['Kalshi exact effective suspension amendment and fee schedule/rounding priority','US historical rule-version/contract amendment coverage and mandatory settlement-charge applicability','Private charges when an exact all-in account result is required'],
        historical_state_clock='Closed missing evidence, not a further acquisition target',net_qualified=False)

def annotate(result):
    f=facts();result['retained_review'].update(version=VERSION,us_rulebook_review=f,
        note='US hierarchy and settlement-description priority now explicit; dated rulebook alone is not an effective-date notice. Retained economics and prior versions unchanged. No further public acquisition proposed; scoped provider clarification remains.')
    return result
