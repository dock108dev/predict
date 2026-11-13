"""Owned native sportsbook reference capture from SQL facts and reviewed bindings."""
from copy import deepcopy
from fractions import Fraction
import json


def owned_median_evidence(row, inputs, source, *, best_payout=False, diagnostics=None, registry=None, native=None):
    from app.storage.store import hashed, stamp
    from .cashflows import exact_wire
    from .game_phase import sgo_event_status, sporting_phase
    from .line_reference import scoring
    from .occurrence_matching import OccurrenceResolver
    from .snapshot_identity import project
    from .sgo_reference import BEST_BOOKS, OPPOSITE
    from .sgo_rule_evidence import SETTLEMENT, owned_bindings, reviewed_best_payout, reviewed_median, settlement_key

    def missing(reason):
        if diagnostics is not None:
            diagnostics['reason'] = reason
        return None

    try:
        native=next(q for q in inputs['quotes'] if q['id']==row['id']) if native is None else native
        record=native['original_record']; at=stamp(inputs['captured_at'])
        league = row['league']; market = record['market_identity']['family']
        settlement = settlement_key(league, market, 'game')
        phase=(source.get('lifecycle') or {}).get('state')
        if (record['quote']['source']['provider'] not in ('kalshi','polymarket_us','novig')
                or not native.get('binding',{}).get('verified') or not row.get('quote_revision')
                or phase not in ('scheduled','live') or (phase=='scheduled') != (at<stamp(native['start_at']))):
            return missing('sgo_offer_native_contract_unverified')
        registry = owned_bindings() if registry is None else registry
        if not best_payout and settlement != SETTLEMENT:
            return missing('sgo_reference_book_rules_unverified')
        anchors={}
        for item in inputs['quotes']+inputs['references']:
            r=item.get('original_record') or {}; s=(r.get('quote') or {}).get('source') or {}
            if s.get('provider')=='sportsgameodds' and s.get('native_event_id') in inputs.get('sgo_reference_events',{}):
                anchors.setdefault(s['native_event_id'],r)
        if not anchors:
            return missing('sgo_reference_pair_unavailable')
        resolved=OccurrenceResolver().resolve(deepcopy([record]+list(anchors.values())),clock=inputs['captured_at'])
        match=resolved[0]['quote'].get('occurrence_match') or {}
        methods=('shared_provider_id','reviewed_source_id','local_reviewed_override')
        if (match.get('status')!='matched' or match.get('estimated') is not False
                or match.get('conflicts') or match.get('method') not in methods
                or len({member['provider'] for member in match.get('members', [])}) < 2):
            return missing('sgo_reference_occurrence_unverified')
        occurrence=match['occurrence_id']; native_key=(record['quote']['source']['provider'],record['quote']['source']['native_event_id'])
        projected=project([deepcopy(native)],{'scenario':'decisive_only'},leagues=(league,),occurrences={native_key:occurrence})[0]
        scope=projected.get('snapshot_identity') or {}
        predicate=((projected.get('native_contract') or {}).get('same_outcome') or {}).get('predicate') or {}
        if (not projected.get('snapshot_supported') or scope.get('method')!='validated_ordinary_occurrence'
                or scope.get('scoring_basis')!='retained source scoring evidence' or scope.get('scoring')!=scoring(league)
                or predicate.get('domain')!=('combined_score' if market=='total' else 'home_margin')
                or predicate.get('operator') not in ('gt','ge','lt','le')):
            return missing('sgo_reference_settlement_unverified')
        higher = predicate['operator'] in ('gt','ge')
        threshold = Fraction(predicate['threshold'])
        # The checked source predicate can use an inclusive integer threshold
        # for a half-point line. Books identify the exact original signed line.
        signed_line = None if market == 'moneyline' else Fraction(record['selection']['signed_line'])
        if market == 'moneyline':
            if threshold != 0:
                return missing('sgo_reference_settlement_unverified')
            side, line = ('home' if higher else 'away'), None
        elif market == 'spread':
            side, line = ('home' if higher else 'away'), exact_wire(signed_line)
        else:
            side, line = ('over' if higher else 'under'), exact_wire(signed_line)
        opposing = OPPOSITE[side]
        opposing_line = -signed_line if market == 'spread' else signed_line
        if (market != 'moneyline' and threshold.denominator == 1
                and scope.get('equality_basis') != 'retained predicate/equality'):
            return missing('sgo_reference_settlement_unverified')
        occurrence_evidence='occurrence:'+hashed(match)
        native_evidence='native-scoring:'+hashed([record.get('comparison_source_metadata'),scope,predicate])
        candidates=[]; reason='sgo_reference_pair_unavailable'
        matched_reference = False
        timing_gap = False
        rules_gap = False
        for observed in resolved[1:]:
            m=observed['quote'].get('occurrence_match') or {}
            if (m.get('status')!='matched' or m.get('estimated') is not False or m.get('method') not in methods
                    or m.get('conflicts') or m.get('occurrence_id')!=occurrence):
                continue
            if best_payout and stamp(native['start_at']) != stamp(observed['event']['scheduled_start']):
                reason='sgo_reference_occurrence_unverified'
                continue
            matched_reference = True
            event_id=observed['quote']['source']['native_event_id']
            live_start = max(stamp(native['start_at']), stamp(observed['event']['scheduled_start'])) if phase == 'live' else None
            event=inputs['sgo_reference_events'][event_id]; frame=(event.get('frame') or {}).get('facts') or {}
            if frame.get('provider')!='sportsgameodds' or frame.get('event_id')!=event_id:
                continue
            if live_start is not None:
                status = (frame.get('event_context') or {}).get('status') or {}
                if sporting_phase({'status': sgo_event_status(status)})['state'] != 'live':
                    timing_gap = True
                    continue
            members=dict(frame['members'])
            if len(members)!=len(frame['members']):
                continue
            frame_id=frame['receipt_sha256']; frame_at=frame['received_at']; quotes=[]; entries={}
            for entry in event['rows']:
                f=entry['facts']; dep='sgo-reference:'+entry['id']
                if (members.get(entry['id'])!=entry['revision']
                        or best_payout and f.get('venue') not in BEST_BOOKS
                        or f.get('provider')!='sportsgameodds' or f.get('event_id')!=event_id
                        or f.get('league')!=league or f.get('market')!=market or f.get('period')!='game'
                        or f.get('phase')!=('pregame' if phase=='scheduled' else 'live')
                        or f.get('available') is not True):
                    continue
                if f.get('side') not in (side, opposing):
                    continue
                expected_line = opposing_line if f['side'] == opposing else signed_line
                fact_line = None if f.get('line') is None else Fraction(f['line'])
                if fact_line != expected_line:
                    continue
                q={k:f.get(k) for k in ('provider','venue','event_id','odd_id','opposing_odd_id','league','market','period',
                    'phase','side','line','price_american','source_at','received_at','available')}
                q.update(frame_id=frame_id,frame_received_at=frame_at)
                quotes.append(q);entries[(q['venue'],q['odd_id'])]=(dep,inputs['dependencies'].get(dep))
            contract=dict(event_id=event_id,league=league,phase='pregame' if phase=='scheduled' else 'live',period='game',
                market=market,side=side,line=line,settlement=settlement,settlement_evidence=native_evidence,
                occurrence_evidence=occurrence_evidence,frame_id=frame_id,frame_received_at=frame_at)
            if live_start is not None:
                contract['starts_at'] = live_start.isoformat()
            calculate = reviewed_best_payout if best_payout else reviewed_median
            result,witness=calculate(quotes,contract,at=inputs['captured_at'],evaluated_venue=row['venue'],registry=registry)
            if not result.get('available'):
                exclusions = set(result.get('exclusions', {}).values())
                rules_gap |= bool(exclusions & {'exact_jurisdiction_binding_unavailable', 'jurisdiction_rules_unreviewed',
                                                'reviewed_jurisdiction_registry_unavailable'})
                timing_gap |= bool(exclusions & {'source_stale', 'reference_pre_start', 'clock_future',
                                                 'source_clock_unknown', 'source_clock_invalid'})
                continue
            evidence=json.loads(witness.wire)['basis']['contributors']; deps=[]
            for contributor in evidence:
                for item in contributor['inputs']:
                    dep,revision=entries[(contributor['venue'],item['odd_id'])]
                    deps.append(dict(item,venue=contributor['venue'],dependency=dep,expected_revision=revision,state='available'))
            if any(dep['expected_revision'] is None for dep in deps):
                reason = 'sgo_reference_evidence_unavailable'
                continue
            candidate=dict(witness=witness.wire,binding=dict(verified=True,row_id=row['id'],row_revision=row['quote_revision'],
                contract=contract,occurrence_evidence=occurrence_evidence,settlement_evidence=native_evidence),dependencies=deps,
                selected_identity=scope,selected_predicate=predicate)
            candidates.append((min(stamp(item['source_at']) for c in evidence for item in c['inputs']),result['probability'],candidate))
        if not candidates:
            if not matched_reference:
                return missing('sgo_reference_occurrence_unverified')
            if reason == 'sgo_reference_pair_unavailable':
                if rules_gap:
                    reason = 'sgo_reference_book_rules_unverified'
                elif timing_gap:
                    reason = 'sgo_reference_pair_timing_unverified'
            return missing(reason)
        latest=max(c[0] for c in candidates); winners=[c for c in candidates if c[0]==latest]
        if len({c[1] for c in winners})!=1:return missing('reference_frames_conflict')
        return sorted(winners,key=lambda c:c[2]['witness'])[0][2]
    except (KeyError,StopIteration,TypeError,ValueError,ArithmeticError,OSError):
        return missing('sgo_reference_evidence_unavailable')
