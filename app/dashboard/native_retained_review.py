"""Opt-in interpretation of one immutable run; original calculations stay unchanged."""
from copy import deepcopy
from decimal import Decimal
from .native_acquisition_review import VERSION as ACQUIRED_VERSION
from .native_public_review import VERSION as PUBLIC_VERSION
from .native_rule_review import VERSION as RULE_VERSION
from .native_filing_review import VERSION as FILING_VERSION
from .native_precedence_review import VERSION as PRECEDENCE_VERSION
from .native_us_rulebook_review import VERSION as US_RULEBOOK_VERSION

VERSION='atl-gb-native-review-1'
SESSION='184493b2-9bc6-471c-9085-2f73390c7841'
CUTOFF='165-d465e5a4dbe44a4d1e1a288adb381f5a7890e830d71c9c98e0b983ca9308cefd'
SPEC='cab3ac9d401c440410e2cf0840dce1e5ea057be8ee7ee101d4d0d787fe2b6076'


def point_for(snapshot,point,version):
    if version not in (VERSION,ACQUIRED_VERSION,PUBLIC_VERSION,RULE_VERSION,FILING_VERSION,PRECEDENCE_VERSION,US_RULEBOOK_VERSION) or snapshot['session_id']!=SESSION or snapshot['durable_cursor']!=CUTOFF:
        raise ValueError('Review does not bind this exact retained session/cutoff')
    point=deepcopy(point)
    for card in point['cards']:
        age=card['age_seconds']
        card['receipt_stale']=age is None or Decimal(age)<0 or Decimal(age)>15
    return point


def annotate(result,point,version=VERSION):
    states={c['book']['id']:c['book']['market_state'] for c in point['cards'] if c['book']}
    def reasons(items,book_id):
        return ['Market state unknown at cutoff' if x=='Market is not active at cutoff' and states.get(book_id)=='unknown' else x for x in items]
    for c in result['contracts']:
        c['warnings']=reasons(c['warnings'],c['book_id'])
    for candidate in result['candidates']:
        for leg in candidate['legs']:
            leg['warnings']=reasons(leg['warnings'],leg['book_id'])
            leg['reasons']=reasons(leg['reasons'],leg['book_id'])
        candidate['reasons']=list(dict.fromkeys(x for leg in candidate['legs'] for x in leg['reasons']))+[
            x for x in candidate['reasons'] if x=='Books more than 5 seconds apart at cutoff']
        candidate['reasons']+=['Settlement equivalence unresolved: overtime, cancellation and exceptional outcomes',
            'Clock offset uncertainty unmeasured; source timestamps are not proven delivery latency']
        candidate['review_before_fees']=dict(available=candidate['notional'] is not None,
            purchase_notional=candidate['notional'],normal_winner_payout=candidate['modeled_quantity'],
            normal_winner_margin=None if candidate['notional'] is None else str(Decimal(candidate['modeled_quantity'])-Decimal(candidate['notional'])),
            qualification='Arithmetic only, conditional on both legs filling and normal winner settlement; not net profit')
    leg=result['ev']['leg'];leg['reasons']=reasons(leg['reasons'],leg['book_id']);leg['warnings']=reasons(leg['warnings'],leg['book_id'])
    result['retained_review']=dict(version=VERSION,session=SESSION,cutoff=CUTOFF,spec_sha256=SPEC,
        receipt_limit_seconds=15,receipt_skew_limit_seconds=5,original_preserved=True,
        corrections=['Unknown market state is not inactive','Receipt age uses frozen run 15-second limit, not legacy 30 seconds'],
        note='Retrospective interpretation, not information newly available at the historical cutoff. No fee or settlement substitution.')
    if version in (ACQUIRED_VERSION,PUBLIC_VERSION,RULE_VERSION,FILING_VERSION,PRECEDENCE_VERSION,US_RULEBOOK_VERSION):
        from .native_acquisition_review import annotate as acquired_annotation
        result=acquired_annotation(result)
        if version in (PUBLIC_VERSION,RULE_VERSION,FILING_VERSION,PRECEDENCE_VERSION,US_RULEBOOK_VERSION):
            from .native_public_review import annotate as public_annotation
            result=public_annotation(result)
        if version in (RULE_VERSION,FILING_VERSION,PRECEDENCE_VERSION,US_RULEBOOK_VERSION):
            from .native_rule_review import annotate as rule_annotation
            result=rule_annotation(result)
        if version in (FILING_VERSION,PRECEDENCE_VERSION,US_RULEBOOK_VERSION):
            from .native_filing_review import annotate as filing_annotation
            result=filing_annotation(result)
        if version in (PRECEDENCE_VERSION,US_RULEBOOK_VERSION):
            from .native_precedence_review import annotate as precedence_annotation
            result=precedence_annotation(result)
        if version==US_RULEBOOK_VERSION:
            from .native_us_rulebook_review import annotate as us_rulebook_annotation
            result=us_rulebook_annotation(result)
        return result
    return result
