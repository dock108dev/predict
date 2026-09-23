"""Third opt-in interpretation; newly acquired documents never rewrite prior reviews."""
from datetime import datetime
from decimal import Decimal,localcontext,ROUND_HALF_EVEN
from pathlib import Path
import hashlib,json
VERSION='atl-gb-native-review-3'
ROOT=Path(__file__).resolve().parents[2]/'evidence/b6-public-prerequisites-20260923-v1/acquisition'
EFFECTIVE='2026-09-17T04:00:00+00:00'
AS_OF='2026-09-23T16:20:14.716584+00:00'
HASHES={'06-response.bin': '16ae9838aacaeea22e5bf40c1328755d6b2d07f03dc637bec2a28e76d7f255cc', '01-response.bin': '19578b71cd63da63cc2894c60542ef06bb5de56b9366add56f07cee645cfca4b', 'result.json': 'bafbb6a0458f7cdc802f6dfecb1b713522b3c00df34c99527910cc98094ee5ed', 'us-link-review.json': '0e698eec5055470f2892aa4984b902b8c082cda661a33a159425a700ce7f1893', 'consumed.json': 'e2c39dfb2ef676c363c26a10a791850e5df3bb423455e32e9726efd8446b4afb', 'requests.json': 'da7be6a8109dc8bf915dc75dd9109ddf059b85467986d480283a5d7f402f53d8', '03-response.bin': '24fcb758e11d6c1d8bd412dd12e5afd1725d390ffb52233786963c7d64cb564e', '04-response.bin': 'e577577568e436423c5d377ee89d236becaf4a24161e42cdde721f86642f3dc1', '05-response.bin': 'e7aa2287e34edbb5462c1030a518b2d268e0a5deb54f039bee6cacb3f92820b7', '02-response.bin': '7591cf0fb277eaf8fac8aedaf1645e58b61dacb22b5fed20ba7d8ea9f76ffa22'}

def facts():
    for name,h in HASHES.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=h:raise ValueError('Public document evidence mismatch: '+name)
    ledger=json.loads((ROOT/'requests.json').read_text())
    return dict(summary='Six official documents acquired; conditional US contract slot unused. Dated US theta0.0695 resolves the coefficient conflict. Exact total net returns remain unavailable.',
        acquisition='b6-public-prerequisites-20260923-v1',hashes=HASHES,
        sources=[{k:r.get(k) for k in ('url','sha256','status','start','headers_received','end','body')} for r in ledger],
        us_fee=dict(theta='0.0695',effective_from=EFFECTIVE,native_market='779756',native_event='108683',historical_coefficient_resolved=True,
                    precedence='Exchange-wide effective September17 schedule supersedes retained July1 theta0.06; exact retained market coefficient agrees.',
                    rounding='Per-fill half-even cents, reduced as needed by cumulative exact-fee cap; resting-order allocation unknown.',
                    settlement_charges=None,account_rebate_tier=None),
        kalshi_terms=dict(current_series_link='KXNFLGAME / FOOTBALLGAMEWIN',historical_applicability=False,
            reason='No effective date/version history in acquired current contract terms; later retrieval does not prove earlier applicability.',
            current_document_findings=['Overtime included unless otherwise specified','Full-game two-team tie pays0.50',
              'Pregame forfeit uses discretionary last fair price; post-kickoff follows official result',
              'Abandonment/suspension distinguishes55-minute and league-final branches; exact55-minute boundary not resolved by strict before/after wording',
              'Postponement requires rescheduled game to begin within48h; otherwise fair price',
              'Venue/home-away changes and pre-expiration disqualification have distinct branches',
              'Source agencies are hierarchical; post-expiration revisions excluded; Rule7.1 review discretion retained']),
        state_time=dict(us_open_enum='MARKET_STATE_OPEN means open for trading',
            kalshi_book_is_not_state='Resting orders remain visible during trading/exchange pauses',
            timestamp_examples='Kalshi ts/ts_ms and US transactTime are documented fields; examples alone do not bound clock offsets or establish state validity through gaps',
            historical_state=None,historical_clock_uncertainty=None,continuous_state_validity=None),
        excluded='Blocked Kalshi fee PDF was not requested. No credentials, streams, credits, retries or additional discovery. All attempts consumed.')

def us_entry_bound(fills,at,coefficient):
    """Conditional new all-taker order, no prior fills; allocation-independent cap."""
    unavailable=dict(available=False,lower=None,upper=None,exact_fee=None)
    when=datetime.fromisoformat(at.replace('Z','+00:00'))
    if when.utcoffset() is None or when<datetime.fromisoformat(EFFECTIVE) or when>datetime.fromisoformat(AS_OF) or coefficient!='0.0695' or not fills:
        return dict(unavailable,reason='Dated schedule/coefficient or modeled fills unsupported')
    with localcontext() as ctx:
        ctx.prec=100
        raw=Decimal(0);quantity=Decimal(0)
        for fill in fills:
            if not isinstance(fill.get('price'),str) or not isinstance(fill.get('quantity'),str):raise ValueError('decimal strings required')
            p=Decimal(fill['price']);q=Decimal(fill['quantity'])
            if not p.is_finite() or not q.is_finite() or not Decimal('.01')<=p<=Decimal('.99') or q<=0:raise ValueError('unsupported price/quantity')
            if len(p.as_tuple().digits)>24 or len(q.as_tuple().digits)>24 or abs(q.as_tuple().exponent)>12:raise ValueError('bounded decimal required')
            raw+=Decimal('.0695')*q*p*(1-p);quantity+=q
        cap=raw.quantize(Decimal('.01'),rounding=ROUND_HALF_EVEN)
    return dict(available=True,lower='0.00',upper=str(cap),exact_fee=None,raw_model_fee=str(raw),quantity=str(quantity),
        coefficient='0.0695',effective_from=EFFECTIVE,fee_document_sha256=HASHES['03-response.bin'],
        qualification='Conditional gross US entry commission bound for these modeled all-taker purchases as one new order. Unknown counterparty split; lower bound intentionally loose. Excludes Kalshi fees, private charges, settlement and optional later rebates. Not qualified net profit.')

def annotate(result):
    evidence=facts()
    old=result['retained_review']['acquired_evidence']
    result['retained_review'].update(version=VERSION,prior_acquisition=old,acquired_evidence=evidence,resolved_us_fee_coefficient=True,
        note='Retrospective review3: explicit dated US schedule supports coefficient/rounding only. Current undated Kalshi terms are not promoted to historical settlement. Original and reviews1/2 remain unchanged.')
    unresolved='US coefficient resolved; exact split-dependent commission, account terms and settlement charges remain unavailable'
    for candidate in result['candidates']:
        candidate['reasons']=[unresolved if r=='Retained coefficient not supported by pinned schedule' else r for r in candidate['reasons']]
        for leg in candidate['legs']:
            if leg['venue']=='polymarket_us':
                leg['reasons']=[unresolved if r=='Retained coefficient not supported by pinned schedule' else r for r in leg['reasons']]
                leg['review_entry_fee_bound']=us_entry_bound(leg['fills'],result['cutoff'],result['assessment']['pmus_coefficient'])
                leg['review_fee_audit_note']='Original fee audit preserved; new dated schedule interpretation and bound are separate.'
    leg=result['ev']['leg']
    if leg['venue']=='polymarket_us':
        leg['reasons']=[unresolved if r=='Retained coefficient not supported by pinned schedule' else r for r in leg['reasons']]
        leg['review_entry_fee_bound']=us_entry_bound(leg['fills'],result['cutoff'],result['assessment']['pmus_coefficient'])
    return result

def reviewed_registry():
    """Separate dated native schedule; the original registry is never modified."""
    evidence=facts()
    from app.fees.engine import Registry
    return Registry(dict(schema=1,schedules=[dict(venue='polymarket_us',product='event_contract',
        version='pmus-2026-09-17-native-review3',coefficient='0.0695',maker_coefficient='0.0125',
        effective_from=EFFECTIVE,effective_to=None,sources=[dict(file='03-response.bin',
        url='https://docs.polymarket.us/fees.md',sha256=HASHES['03-response.bin'],
        retrieved_at=evidence['sources'][2]['end'],status=200)])]))
