"""Fixture-testable publication boundary for qualified SGO references.

The current-row owner must supply current dependency revisions and independently
verified occurrence and settlement bindings. This module does not discover
them or turn provider IDs into proof of native contract equivalence.
"""
from copy import deepcopy
from fractions import Fraction

from .cashflows import exact_wire
from .sgo_reference import validate_witness


def captured_frame(record, capture):
    """Resolve an original quote against a stored co-observation frame."""
    try:
        from fractions import Fraction
        q=record['quote']; s=q['source']; meta=record['comparison_source_metadata']
        frame=capture['frame']['facts']; members=dict(frame['members'])
        digest=frame.get('receipt_sha256')
        if (frame.get('provider')!='sportsgameodds' or frame.get('event_id')!=s['native_event_id']
                or len(members)!=len(frame['members']) or not isinstance(digest,str) or len(digest)!=64
                or any(c not in '0123456789abcdef' for c in digest)):
            return None
        def line(value):return None if value is None else Fraction(value)
        matched=[]
        for entry in capture['rows']:
            fact=entry['facts']
            if (members.get(entry['id']) != entry['revision'] or fact.get('event_id') != s['native_event_id']
                    or fact.get('venue') != q['venue'] or fact.get('odd_id') != s['native_outcome_id']
                    or fact.get('opposing_odd_id') != meta.get('provider_opposing_odd_id')
                    or line(fact.get('line')) != line(record['selection'].get('signed_line'))
                    or fact.get('price_american') != q['original']['value']
                    or fact.get('source_at') != q['times']['source_at']
                    or fact.get('phase') != meta.get('provider_phase')
                    or fact.get('available') is not (q.get('state') == 'available')):
                continue
            matched.append(entry['id'])
        if len(matched)!=1:
            return None
        return {'frame_id':frame['receipt_sha256'],'frame_received_at':frame['received_at']}
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None


def evaluate(row, witness, binding, dependencies, *, at, price_authority, review=None):
    """Calculate one captured row only while every exact contributor is current.

    Each dependency is an independently read current-row fact, not the witness
    itself. The expected revision was captured alongside the calculation; the
    current revision must be read again when publishing or revalidating.
    """
    def unavailable(reason):
        return {'available': False, 'reason': reason, 'probability': None,
                'gross_return_percent': None, 'conditional_trade_benchmark': {'available': False, 'reason': reason}}

    validated = validate_witness(witness, at=at)
    if not validated.get('available'):
        return unavailable(validated.get('reason', 'reference_witness_invalid'))
    basis = validated['basis']
    if (not isinstance(binding, dict) or binding.get('verified') is not True
            or row.get('revision') is None
            or not binding.get('occurrence_evidence') or not binding.get('settlement_evidence')
            or binding.get('contract') != basis['contract']
            or binding.get('row_id') != row.get('id')
            or binding.get('row_revision') != row.get('revision')
            or binding.get('occurrence_evidence') != basis['contract'].get('occurrence_evidence')
            or binding.get('settlement_evidence') != basis['contract'].get('settlement_evidence')
            or row.get('venue') != basis['evaluated_venue']):
        return unavailable('sgo_contract_binding_unverified')
    if (not isinstance(price_authority, dict) or price_authority.get('eligible') is not True
            or not price_authority.get('dependency') or not price_authority.get('expected_revision')
            or price_authority.get('expected_revision') != price_authority.get('current_revision')
            or price_authority.get('row_id') != row.get('id')
            or price_authority.get('row_revision') != row.get('revision')):
        return unavailable('source_price_authority_unavailable')
    expected = {}
    for contributor in basis['contributors']:
        for item in contributor['inputs']:
            key = (contributor['venue'], item['odd_id'])
            if key in expected:
                return unavailable('sgo_dependency_ambiguous')
            expected[key] = item
    current = {}
    for dep in dependencies:
        if not isinstance(dep, dict):
            return unavailable('sgo_dependency_invalid')
        key = (dep.get('venue'), dep.get('odd_id'))
        if key in current:
            return unavailable('sgo_dependency_ambiguous')
        current[key] = dep
    if set(current) != set(expected):
        return unavailable('sgo_dependency_missing_or_extra')
    fields = ('frame_id', 'frame_received_at', 'odd_id', 'opposing_odd_id', 'side', 'line', 'price_american',
              'source_at', 'received_at', 'settlement', 'settlement_evidence', 'jurisdiction', 'rule_source', 'rule_reviewed_at')
    for key, item in expected.items():
        dep = current[key]
        if (not dep.get('dependency') or not dep.get('expected_revision')
                or dep.get('current_revision') != dep['expected_revision']
                or dep.get('state') != 'available'
                or any(dep.get(field) != item.get(field) for field in fields)):
            return unavailable('sgo_contributor_changed_or_unavailable')
    try:
        p, cost = Fraction(validated['probability']), Fraction(row['cost_per_normal_claim'])
        if not 0 < p < 1 or not 0 < cost <= 1:
            return unavailable('sgo_price_or_probability_invalid')
        gross = exact_wire(100 * (p / cost - 1))
        reference = {'available': True, 'venue': basis['named_venue'] or 'sportsgameodds_books',
                     'method': basis['version'], 'contributors': deepcopy(basis['contributors']),
                     'exclusions': deepcopy(basis['exclusions']), 'basis_sha256': validated['basis_sha256'],
                     'maximum_age_seconds': basis['maximum_age_seconds'],
                     'fair_decimal_odds': exact_wire(1 / p),
                     'conditioning': validated['conditioning'], 'full_state_probability': False}
        metric_row = dict(row, probability=str(p), gross_return_percent=gross,
                          snapshot_benchmark={'method': basis['version'], 'probability': str(p),
                                              'basis_sha256': validated['basis_sha256']})
        from .conditional_benchmark import snapshot_metric
        fee = snapshot_metric(metric_row, at=at, review=review)
        return {'available': True, 'probability': str(p), 'gross_return_percent': gross,
                'reference_calculation': reference, 'conditional_trade_benchmark': fee,
                'dependency_ids': [current[k]['dependency'] for k in sorted(current)]}
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return unavailable('sgo_price_or_fee_inputs_invalid')


def owned_reference_evidence(row, inputs, source):
    """Build a narrow Pinnacle candidate from captured SQL originals and rules.

    The only reviewed bookmaker scoring rule currently owned is Pinnacle's.
    Other bookmakers remain ineligible until their own scoring rules are
    reviewed. Both original observations and current-row revision tokens must
    exist in the same captured frame; no caller-provided verification flag is
    used as a substitute for occurrence and native scoring evidence.
    """
    from copy import deepcopy
    from hashlib import sha256
    from pathlib import Path
    from app.storage.current_rows import contract_id
    from app.storage.store import hashed, stamp
    from .line_reference import RULE_PATH, scoring
    from .occurrence_matching import OccurrenceResolver
    from .snapshot_benchmark import market_key, reference_row
    from .snapshot_identity import project
    from .sgo_reference import capture_witness
    try:
        native = next(q for q in inputs['quotes'] if q['id'] == row['id'])
        record = native['original_record']
        phase = (source.get('lifecycle') or {}).get('state')
        if (record['quote']['source']['provider'] not in ('kalshi', 'polymarket_us', 'novig')
                or not native.get('binding', {}).get('verified') or not row.get('quote_revision')
                or phase not in ('scheduled', 'live')
                or (phase == 'scheduled') != (stamp(inputs['captured_at']) < stamp(native['start_at']))):
            return None
        refs = [r for r in inputs['references'] if r.get('original_record')
                and r['original_record']['quote']['source']['provider'] == 'sportsgameodds'
                and r['original_record']['quote']['venue'] == 'pinnacle']
        if not refs:
            return None
        all_records = deepcopy([record] + [r['original_record'] for r in refs])
        resolved = OccurrenceResolver().resolve(all_records, clock=inputs['captured_at'])
        native_match = resolved[0]['quote'].get('occurrence_match') or {}
        explicit_methods = ('shared_provider_id', 'reviewed_source_id', 'local_reviewed_override')
        if (native_match.get('status') != 'matched' or native_match.get('conflicts')
                or native_match.get('estimated') is not False or native_match.get('method') not in explicit_methods):
            return None
        occurrence = native_match['occurrence_id']
        matched = []
        for r, resolved_ref in zip(refs, resolved[1:]):
            match = resolved_ref['quote'].get('occurrence_match') or {}
            if (match.get('status') == 'matched' and not match.get('conflicts')
                    and match.get('estimated') is False and match.get('method') in explicit_methods
                    and match.get('occurrence_id') == occurrence
                    and len({m['provider'] for m in match.get('members', [])}) > 1):
                item = deepcopy(r)
                item['original_record']['comparison_scope'] = scoring(row['league'])
                matched.append(item)
        if not matched:
            return None
        occurrence_map = {(x['quote']['source']['provider'], x['quote']['source']['native_event_id']): occurrence
                          for x in resolved if (x['quote'].get('occurrence_match') or {}).get('occurrence_id') == occurrence}
        projected = project([deepcopy(native)] + [reference_row(r) for r in matched], {'scenario': 'decisive_only'},
                            leagues=('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL'), occurrences=occurrence_map)
        selected = projected[0]
        native_scope = selected.get('snapshot_identity') or {}
        if (native_scope.get('method') != 'validated_ordinary_occurrence'
                or native_scope.get('scoring_basis') != 'retained source scoring evidence'
                or native_scope.get('scoring') != scoring(row['league'])):
            return None
        key = market_key(selected)
        predicate = (selected.get('native_contract') or {}).get('same_outcome', {}).get('predicate') or {}
        if key is None or predicate.get('operator') not in ('gt', 'lt', 'ge', 'le'):
            return None
        desired = 'gt' if predicate['operator'] in ('gt', 'ge') else 'lt'
        groups = {}
        for ref in projected[1:]:
            if market_key(ref) != key:
                continue
            r = ref['original_record']; q = r['quote']; source = q['source']; meta = r.get('comparison_source_metadata') or {}
            if (meta.get('provider_phase') != ('pregame' if phase == 'scheduled' else 'live') or not meta.get('provider_opposing_odd_id')
                    or q.get('state') != 'available' or q['original'].get('units') != 'american_odds'):
                continue
            if phase == 'live' and (not q['times'].get('source_at')
                                    or stamp(q['times']['source_at']) < stamp(native['start_at'])):
                continue
            observed=captured_frame(r, (inputs.get('sgo_reference_events') or {}).get(source['native_event_id']) or {})
            if observed is None:
                # A retained exact same-receipt pair is independently evidenced
                # by its original records, even without a later shared frame.
                observed=dict(frame_id=q['provenance'].get('sha256'),frame_received_at=q['times']['received_at'])
            frame = (source['native_event_id'], observed['frame_id'], observed['frame_received_at'])
            groups.setdefault(frame, []).append(ref)
        rule_path = Path(__file__).resolve().parents[2] / RULE_PATH
        settlement = 'pinnacle-normal-score:' + sha256(rule_path.read_bytes()).hexdigest()
        occurrence_evidence = 'occurrence:' + hashed(native_match)
        candidates = []
        for (event_id, frame_id, frame_received_at), group in sorted(groups.items()):
            if len(group) != 2 or not frame_id:
                continue
            by_operator = {}
            for ref in group:
                r=ref['original_record']; q=r['quote']; m=r['market_identity']; selection=r['selection']
                operator=(ref.get('native_contract') or {}).get('same_outcome', {}).get('predicate', {}).get('operator')
                if operator not in ('gt', 'lt') or operator in by_operator:
                    break
                side = selection['predicate'] if m['family'] == 'total' else ('home' if selection['participant'] == r['event']['home'] else 'away' if selection['participant'] == r['event']['away'] else None)
                if side is None:
                    break
                cid=contract_id(r); revision=inputs['dependencies'].get(cid)
                if not revision:
                    break
                meta=r['comparison_source_metadata']
                quote=dict(event_id=event_id, league=row['league'], phase='pregame' if phase == 'scheduled' else 'live', period='game',
                    market=m['family'], side=side, line=selection.get('signed_line'), venue='pinnacle',
                    price_american=q['original']['value'], source_at=q['times']['source_at'],
                    received_at=q['times']['received_at'], frame_received_at=frame_received_at, available=True, odd_id=q['source']['native_outcome_id'],
                    opposing_odd_id=meta['provider_opposing_odd_id'], frame_id=frame_id,
                    settlement='pinnacle-normal-score', settlement_evidence=settlement)
                by_operator[operator]=(quote,cid,revision)
            if set(by_operator) != {'gt', 'lt'}:
                continue
            selected_quote = by_operator[desired][0]
            contract = {k:selected_quote[k] for k in ('event_id','league','phase','period','market','side','line','settlement','settlement_evidence','frame_id','frame_received_at')}
            contract['occurrence_evidence']=occurrence_evidence
            quotes=[v[0] for v in by_operator.values()]
            result,witness=capture_witness(quotes, contract, at=inputs['captured_at'], evaluated_venue=row['venue'], named_venue='pinnacle')
            if not result['available']:
                continue
            deps=[dict(q,dependency=cid,expected_revision=revision,state='available') for q,cid,revision in by_operator.values()]
            candidate={'witness':witness.wire, 'binding':dict(verified=True,row_id=row['id'],row_revision=row['quote_revision'],
                contract=contract,occurrence_evidence=occurrence_evidence,settlement_evidence=settlement), 'dependencies':deps}
            candidates.append((min(stamp(q['source_at']) for q in quotes), result['probability'], candidate))
        if not candidates:
            return None
        latest=max(item[0] for item in candidates)
        finalists=[item for item in candidates if item[0] == latest]
        if len({item[1] for item in finalists}) != 1:
            return None
        return sorted(finalists,key=lambda item: item[2]['witness'])[0][2]
    except (KeyError, StopIteration, TypeError, ValueError, ArithmeticError, OSError):
        return None


def bind_captured(row, source, inputs, *, selected_venue='pinnacle'):
    """Adapt ordinary publication's captured dependency map to the SGO boundary.

    Only the explicitly selected SGO reference mode may call this. Missing
    upstream evidence remains unavailable. Captured reference dependencies are
    carried into ordinary publication's existing current-row invalidation path.
    """
    from datetime import timedelta
    from app.dashboard.current_contract import stamp
    from .sgo_reference import ContributorFrameWitness
    missing = {'available': False, 'reason': 'sgo_reference_evidence_unavailable'}
    if selected_venue != 'pinnacle':
        return missing, []
    at = stamp(inputs['captured_at'])
    if (source.get('reasons') or not source.get('dependency') or not source.get('expected')
            or not source.get('current_until') or stamp(source['current_until']) < at):
        return missing, []
    from .sgo_median_publication import owned_median_evidence
    # Versioned policy is named Pinnacle, then reviewed median; each method is
    # disclosed on the resulting reference and bound into its witness revision.
    for produce in (owned_reference_evidence,owned_median_evidence):
        captured=produce(row,inputs,source)
        if not isinstance(captured,dict) or not isinstance(captured.get('witness'),str):continue
        facts=captured.get('dependencies')
        if not isinstance(facts,list):continue
        dependencies,authorities=[],[]
        try:
            for fact in facts:
                dep=dict(fact);expected=dep['expected_revision'];current=inputs['dependencies'].get(dep['dependency'])
                if not expected or not current or current[:3]!=expected[:3]:raise ValueError('dependency_changed')
                dep['current_revision']=current;dep['expected_revision']=current;dependencies.append(dep)
                authorities.append(dict(dependency=dep['dependency'],expected=expected,
                    venue=dep['venue'],provider='sportsgameodds',reasons=[],source_at=dep['source_at']))
            offered=dict(row,revision=row.get('revision',row.get('quote_revision')))
            price_authority=dict(eligible=True,dependency=source['dependency'],
                expected_revision=source['expected'],current_revision=source['expected'],
                row_id=offered['id'],row_revision=offered.get('revision'))
            result=evaluate(offered,ContributorFrameWitness(captured['witness']),captured.get('binding'),
                            dependencies,at=inputs['captured_at'],price_authority=price_authority,review=captured.get('review'))
            if not result.get('available'):continue
            result['reference_calculation']['selection_policy']='sgo-pinnacle-then-reviewed-median-1'
            maximum_age=result['reference_calculation']['maximum_age_seconds']
            for authority in authorities:
                authority['current_until']=(stamp(authority.pop('source_at'))+timedelta(seconds=maximum_age)).isoformat()
            return result,authorities
        except (KeyError,TypeError,ValueError,ArithmeticError):
            continue
    return missing, []
