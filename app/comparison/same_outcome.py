"""One exact sporting-outcome identity for matching and invalidation.

Source numbers and side labels stay in the original observation. Only this key
uses integer-score equivalence; price subtraction remains the existing engine.
"""
from copy import deepcopy
from fractions import Fraction
import re
import json

from .domain import LEAGUES, ExactNumber, ScorePredicate, EqualityDescriptor

VERSION = 'predict-same-outcome-1'


def _unavailable_descriptor(record, scoring, reason, missing):
    return dict(version=VERSION,predicate=None,equality=None,
        normal_payout={k:record['quote'].get('original', {}).get(k) for k in ('payout','payout_units','quantity_units')},
        scoring=deepcopy(scoring),reason=reason,missing_fields=list(missing))


def descriptor(record, *, scoring):
    """Retain explicit native inequality/equality beside display selections."""
    event = record['event'];market = record['market_identity'];quote = record['quote']
    meta = record.get('comparison_source_metadata', {})
    admission = meta.get('comparison_admission', {})
    if admission.get('supported') is False:
        return _unavailable_descriptor(record,scoring,admission.get('reason','comparison_predicate_missing'),
            admission.get('missing_fields',['predicate']))
    selection = record['selection'];family = market.get('family')
    fact = meta.get('source_predicate') or {}
    native_id = quote.get('source', {}).get('native_outcome_id')
    side = next((s for s in fact.get('outcomes', []) if s.get('native_id') == native_id), {})
    predicate = None;equality = None;reason = None
    if fact and not side:
        return _unavailable_descriptor(record,scoring,'comparison_predicate_native_side_conflict',['native_outcome_id'])
    if fact and side:
        try:
            line = Fraction(str(fact['line']))
            if (fact.get('family') != family or fact.get('period') != market.get('period') or
                    fact.get('competition') != event.get('competition') or
                    fact.get('unit') != ('runs' if event.get('competition') == 'MLB' else 'goals' if event.get('competition') == 'NHL' else 'points') or
                    (family == 'total' and fact.get('participant') != 'combined') or
                    (family == 'spread' and fact.get('participant') not in (event.get('home'),event.get('away'))) or
                    (market.get('line') is None and family!='moneyline') or
                    Fraction(str(market.get('line') or '0')) != line):
                return _unavailable_descriptor(record,scoring,'comparison_predicate_source_conflict',['source_predicate','market.line'])
            if (fact.get('native_metadata_sha256') and meta.get('material_sha256') and
                    fact['native_metadata_sha256'] != meta['material_sha256']):
                return _unavailable_descriptor(record,scoring,'comparison_predicate_source_conflict',['source_predicate.native_metadata_sha256'])
            if fact.get('source_threshold') is not None:
                expected_source = -line if family == 'spread' else line
                if Fraction(str(fact['source_threshold'])) != expected_source:
                    return _unavailable_descriptor(record,scoring,'comparison_predicate_source_conflict',['source_predicate.source_threshold'])
        except (ValueError,TypeError,KeyError,ZeroDivisionError):
            return _unavailable_descriptor(record,scoring,'comparison_predicate_source_conflict',['source_predicate.line'])
        domain = 'combined_score' if family == 'total' else 'home_margin'
        threshold = line if domain == 'combined_score' or fact.get('participant') != event.get('home') else -line
        op = side.get('operator')
        if domain == 'home_margin' and fact.get('participant') != event.get('home'):
            op = {'gt':'lt','ge':'le','lt':'gt','le':'ge','eq':'eq','ne':'ne'}.get(op, op)
        predicate = dict(domain=domain, operator=op, threshold=str(threshold), subject_id=None)
        treatment = side.get('equality_treatment', side.get('equality'))
        if isinstance(treatment, dict):
            equality = deepcopy(treatment)
        else:
            treatment = {'refund':'stake_refund','unreachable':'not_feasible'}.get(treatment,treatment)
            if treatment is None:
                treatment = 'not_feasible' if threshold.denominator != 1 else 'predicate' if quote['venue'] == 'kalshi' else 'unknown'
            equality = dict(treatment=treatment,payout=side.get('equality_payout'),
                refund_fees=side.get('refund_fees','unknown') if treatment == 'stake_refund' else 'not_applicable',
                unknown_reason='Native equality/push treatment missing' if treatment == 'unknown' else None)
    else:
        prior = meta.get('same_outcome', {})
        predicate = deepcopy(prior.get('predicate')) or _predicate(event, family, selection)
        equality = None if family == 'moneyline' else deepcopy(prior.get('equality'))
    if predicate and equality is None:
        threshold = Fraction(predicate['threshold'])
        text = '\n'.join(str(v) for values in (meta.get('original_wording'),
            (meta.get('combined_native_binding') or {}).get('original_terms'))
            if isinstance(values,dict) for v in values.values())
        tie = re.search(r'(?:tie|tied)[^.]*\$(0\.\d+)',text,re.IGNORECASE)
        if family == 'moneyline' and tie:
            payout = Fraction(tie[1])
            if selection.get('predicate') == 'not_win':
                payout = 1-payout
            equality = dict(treatment='fraction',payout=str(payout),refund_fees='not_applicable',unknown_reason=None)
        elif threshold.denominator != 1:
            equality = dict(treatment='not_feasible',payout=None,refund_fees='not_applicable',unknown_reason=None)
        elif family == 'moneyline' and any(literal in text.lower() for literal in
                ('equality is settled as no','tie resolves to no','tie, the market resolves to no')):
            equality = dict(treatment='predicate',payout=None,refund_fees='not_applicable',unknown_reason=None)
        elif family != 'moneyline' and quote['venue'] == 'kalshi':
            equality = dict(treatment='predicate',payout=None,refund_fees='not_applicable',unknown_reason=None)
        else:
            equality = dict(treatment='unknown',payout=None,refund_fees='not_applicable',unknown_reason='Native equality/push treatment missing')
    if not predicate:
        reason = 'comparison_predicate_missing'
    elif equality and equality.get('treatment') == 'unknown':
        reason = 'comparison_equality_missing'
    if predicate and equality and reason is None:
        checked = selection_identity(event,family,market.get('period'),scoring,selection,
            predicate=predicate,equality=equality,candidate=True)
        if not checked['supported']:
            return dict(version=VERSION,predicate=predicate,equality=equality,
                normal_payout={k:quote.get('original', {}).get(k) for k in ('payout','payout_units','quantity_units')},
                scoring=deepcopy(scoring),reason=checked['reason'],missing_fields=checked['missing_fields'])
    original = quote.get('original', {})
    normal = {k:original.get(k) for k in ('payout','payout_units','quantity_units')}
    return dict(version=VERSION,predicate=predicate,equality=equality,normal_payout=normal,
        scoring=deepcopy(scoring),reason=reason)


def _result(reason, missing=(), key=None):
    return dict(supported=reason is None, key=None if key is None else json.loads(json.dumps(key)),
        reason=reason, missing_fields=list(missing))


def _predicate(event, family, selection):
    """Legacy exact descriptors; no title inference and no NO/opponent alias."""
    home, away = event.get('home'), event.get('away')
    participant, kind = selection.get('participant'), selection.get('predicate')
    if family == 'moneyline' and participant in (home, away) and kind in ('win', 'not_win'):
        op = ('gt' if participant == home else 'lt') if kind == 'win' else ('le' if participant == home else 'ge')
        return dict(domain='home_margin', operator=op, threshold='0', subject_id=None)
    value = selection.get('signed_line')
    if value is None:
        return None
    value = Fraction(str(value))
    if family == 'spread' and participant in (home, away) and kind == 'cover':
        return dict(domain='home_margin', operator='gt' if participant == home else 'lt',
            threshold=str(-value if participant == home else value), subject_id=None)
    if family == 'total' and kind in ('over', 'under'):
        return dict(domain='combined_score', operator='gt' if kind == 'over' else 'lt',
            threshold=str(value), subject_id=None)
    return None


def _equality_key(equality, predicate):
    value = EqualityDescriptor.from_dict(equality)
    if value.treatment == 'unknown':
        raise ValueError('comparison_equality_missing')
    threshold = Fraction(predicate['threshold'])
    if threshold.denominator == 1 and value.treatment == 'not_feasible':
        raise ValueError('Integer threshold equality is feasible on this scoring domain')
    # Predicate equality is already represented by the exact scoring set.
    # Refund/fraction clauses override that predicate at the ORIGINAL threshold.
    if threshold.denominator != 1 or value.treatment == 'not_feasible':
        return ['predicate']
    if value.treatment == 'predicate':
        return ['predicate']
    return [value.treatment, [threshold.numerator, threshold.denominator],
        None if value.payout is None else list(value.payout.key), value.refund_fees]


def selection_identity(event, family, period, scope, selection, *, predicate=None,
                       equality=None, normal_payout=None, occurrence=None, candidate=False):
    """Return a JSON-safe exact key or a precise local metadata limitation."""
    family = 'moneyline' if family in ('winner', 'team_binary') else family
    league = event.get('competition', event.get('league'))
    if league not in LEAGUES or family not in ('moneyline', 'spread', 'total'):
        return _result('comparison_market_type_unsupported', ['league', 'family'])
    from .sporting_scope import supported
    if not supported(league,family,period):
        return _result('comparison_period_unsupported', ['period'])
    roles = [event.get('home'), event.get('away')]
    if any(not isinstance(p, str) or not p for p in roles) or roles[0] == roles[1]:
        return _result('comparison_participant_roles_missing', ['home', 'away'])
    if selection.get('participant') not in (*roles, None, 'combined', 'tie'):
        return _result('comparison_participant_conflict', ['participant'])
    if predicate is None:
        try:
            predicate = _predicate(event, family, selection)
        except (ValueError, TypeError, ZeroDivisionError):
            predicate = None
    if predicate is None:
        return _result('comparison_predicate_missing', ['predicate'])
    try:
        parsed = ScorePredicate.from_dict(predicate)
        if (family == 'total') != (parsed.domain == 'combined_score'):
            return _result('comparison_predicate_family_conflict', ['predicate.domain'])
        if parsed.domain == 'home_margin' and parsed.subject_id is not None:
            return _result('comparison_predicate_subject_conflict', ['predicate.subject_id'])
        expected = _predicate(event,family,selection)
        if expected is None:
            return _result('comparison_predicate_selection_conflict',['selection'])
        expected_parsed = ScorePredicate.from_dict(expected)
        if family == 'moneyline' and parsed.integer_key != expected_parsed.integer_key:
            return _result('comparison_predicate_selection_conflict',['selection','predicate'])
        if family in ('spread','total'):
            if parsed.operator not in (('gt','ge') if expected_parsed.operator == 'gt' else ('lt','le')):
                return _result('comparison_predicate_selection_conflict',['selection','predicate.operator'])
            if parsed.threshold.value != expected_parsed.threshold.value and parsed.integer_key != expected_parsed.integer_key:
                return _result('comparison_predicate_selection_conflict',['signed_line','predicate.threshold'])
        if equality is None:
            if parsed.threshold.value.denominator != 1:
                equality = dict(treatment='not_feasible', payout=None, refund_fees='not_applicable', unknown_reason=None)
            else:
                return _result('comparison_equality_missing', ['equality'])
        eq_key = _equality_key(equality, predicate)
    except (ValueError, TypeError, KeyError, ZeroDivisionError):
        return _result('comparison_equality_missing' if equality and equality.get('treatment') == 'unknown'
            else 'comparison_predicate_conflict', ['predicate', 'equality'])
    # Named-team NO remains explicit even where the score set can be identical
    # to a strict opposing-team win in leagues without ties.
    named = selection.get('participant') if family == 'moneyline' else None
    kind = selection.get('predicate') if family == 'moneyline' else 'score'
    condition = [league, *roles, family, period, named, kind, list(parsed.integer_key), eq_key]
    if candidate:
        return _result(None, key=[VERSION, 'candidate', *condition])
    missing = []
    if not occurrence:
        missing.append('occurrence')
    scoring = dict(scope or {})
    if scoring.get('overtime') not in ('included', 'excluded'):
        missing.append('overtime')
    if period!='full_game' and scoring.get('overtime')!='excluded':
        missing.append('excluded_later_scoring')
    if league == 'MLB' and scoring.get('extra_innings') not in ('included', 'excluded'):
        missing.append('extra_innings')
    if league == 'NHL' and scoring.get('shootout') not in ('included', 'excluded', 'official_final_score'):
        missing.append('shootout')
    if missing:
        return _result('comparison_occurrence_unresolved' if 'occurrence' in missing else 'comparison_scoring_scope_missing', missing)
    try:
        payout = dict(normal_payout or {})
        face = ExactNumber.parse(payout.get('payout')).key
        if payout.get('payout_units') != 'USD' or payout.get('quantity_units') != 'contracts' or Fraction(*face) <= 0:
            return _result('comparison_normal_payout_unsupported', ['normal_payout'])
    except (ValueError, TypeError, KeyError):
        return _result('comparison_normal_payout_missing', ['normal_payout'])
    scoring_key = [scoring['overtime'], scoring.get('extra_innings', 'not_applicable'),
        scoring.get('shootout', 'not_applicable'), scoring.get('score_domain', 'integer')]
    return _result(None, key=[VERSION, occurrence, *condition, scoring_key, ['USD', 'contracts', list(face)]])


def _record_args(record):
    event, market = record['event'], record['market_identity']
    quote = record['quote']
    metadata = record.get('comparison_source_metadata', {})
    facts = metadata.get('same_outcome', {})
    scope = facts.get('scoring') or metadata.get('scoring_scope', {}).get('scoring') or record.get('comparison_scope', {})
    match = quote.get('occurrence_match', {})
    occurrence = match.get('occurrence_id') if match.get('status') == 'matched' else event.get('game_id')
    return event, market, quote, facts, scope, occurrence


def record_identity(record):
    event, market, quote, facts, scope, occurrence = _record_args(record)
    if facts.get('reason'):
        return _result(facts['reason'],facts.get('missing_fields',['equality' if facts['reason']=='comparison_equality_missing' else 'predicate']))
    return selection_identity(event, market.get('family'), market.get('period'), scope, record['selection'],
        predicate=facts.get('predicate'), equality=facts.get('equality'),
        normal_payout=facts.get('normal_payout') or quote.get('original'), occurrence=occurrence)


def candidate_identity(record):
    """Same condition for dependency neighborhoods, independent of scope health."""
    event, market, _, facts, scope, _ = _record_args(record)
    if facts.get('reason'):
        return _result(facts['reason'],facts.get('missing_fields',['equality' if facts['reason']=='comparison_equality_missing' else 'predicate']))
    return selection_identity(event, market.get('family'), market.get('period'), scope, record['selection'],
        predicate=facts.get('predicate'), equality=facts.get('equality'), candidate=True)


def quote_identity(quote, group, event):
    contract = quote.get('native_contract', {})
    facts = contract.get('same_outcome', {})
    if facts.get('reason'):
        return _result(facts['reason'],facts.get('missing_fields',['equality' if facts['reason']=='comparison_equality_missing' else 'predicate']))
    raw_event = dict(event)
    for participant in event.get('participants', []):
        raw_event[participant['role']] = participant['id']
    match = quote.get('occurrence_match', {})
    scope = facts.get('scoring') or contract.get('scope_evidence', {}).get('scoring') or contract.get('scope', {})
    equality = facts.get('equality')
    normal = facts.get('normal_payout') or quote.get('original')
    # Existing admitted sportsbook odds already normalize to a $1 normal payout
    # through current_contract.price. This is a price-unit bridge, not a claim
    # about their missing fee or exceptional-settlement profiles.
    if group.get('market') == 'winner' and not facts:
        equality = dict(treatment='predicate',payout=None,refund_fees='not_applicable',unknown_reason=None)
    if normal and normal.get('payout_units') == 'USD' and normal.get('units') in ('decimal_odds','american_odds'):
        normal = dict(payout='1',payout_units='USD',quantity_units='contracts')
    return selection_identity(raw_event, group.get('market'), group.get('period'), scope,
        deepcopy(quote.get('binding', {}).get('selection', {})), predicate=facts.get('predicate'),
        equality=equality, normal_payout=normal,
        occurrence=match.get('occurrence_id') if match.get('status') == 'matched' else None)
