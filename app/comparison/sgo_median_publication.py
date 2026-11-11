"""Owned NBA moneyline median capture from SQL facts and reviewed bindings."""
from copy import deepcopy


def owned_median_evidence(row, inputs, source):
    from app.storage.store import hashed, stamp
    from .line_reference import scoring
    from .occurrence_matching import OccurrenceResolver
    from .snapshot_identity import project
    from .sgo_rule_evidence import SETTLEMENT, owned_bindings, reviewed_median
    try:
        registry=owned_bindings()
        if not registry.rows:
            return None
        native=next(q for q in inputs['quotes'] if q['id']==row['id'])
        record=native['original_record']; at=stamp(inputs['captured_at'])
        phase=(source.get('lifecycle') or {}).get('state')
        if (row.get('league')!='NBA' or record['market_identity']['family']!='moneyline'
                or record['quote']['source']['provider'] not in ('kalshi','polymarket_us','novig')
                or not native.get('binding',{}).get('verified') or not row.get('quote_revision')
                or phase not in ('scheduled','live') or (phase=='scheduled') != (at<stamp(native['start_at']))):
            return None
        anchors={}
        for item in inputs['quotes']+inputs['references']:
            r=item.get('original_record') or {}; s=(r.get('quote') or {}).get('source') or {}
            if s.get('provider')=='sportsgameodds' and s.get('native_event_id') in inputs.get('sgo_reference_events',{}):
                anchors.setdefault(s['native_event_id'],r)
        if not anchors:
            return None
        resolved=OccurrenceResolver().resolve(deepcopy([record]+list(anchors.values())),clock=inputs['captured_at'])
        match=resolved[0]['quote'].get('occurrence_match') or {}
        methods=('shared_provider_id','reviewed_source_id','local_reviewed_override')
        if (match.get('status')!='matched' or match.get('estimated') is not False
                or match.get('conflicts') or match.get('method') not in methods):
            return None
        occurrence=match['occurrence_id']; native_key=(record['quote']['source']['provider'],record['quote']['source']['native_event_id'])
        projected=project([deepcopy(native)],{'scenario':'decisive_only'},leagues=('NBA',),occurrences={native_key:occurrence})[0]
        scope=projected.get('snapshot_identity') or {}
        predicate=((projected.get('native_contract') or {}).get('same_outcome') or {}).get('predicate') or {}
        if (not projected.get('snapshot_supported') or scope.get('method')!='validated_ordinary_occurrence'
                or scope.get('scoring_basis')!='retained source scoring evidence' or scope.get('scoring')!=scoring('NBA')
                or predicate.get('domain')!='home_margin' or predicate.get('threshold') not in ('0',0)
                or predicate.get('operator') not in ('gt','ge','lt','le')):
            return None
        side='home' if predicate['operator'] in ('gt','ge') else 'away'
        occurrence_evidence='occurrence:'+hashed(match)
        native_evidence='native-scoring:'+hashed([record.get('comparison_source_metadata'),scope,predicate])
        candidates=[]
        for observed in resolved[1:]:
            m=observed['quote'].get('occurrence_match') or {}
            if (m.get('status')!='matched' or m.get('estimated') is not False or m.get('method') not in methods
                    or m.get('conflicts') or m.get('occurrence_id')!=occurrence):
                continue
            event_id=observed['quote']['source']['native_event_id']
            event=inputs['sgo_reference_events'][event_id]; frame=(event.get('frame') or {}).get('facts') or {}
            if frame.get('provider')!='sportsgameodds' or frame.get('event_id')!=event_id:
                continue
            members=dict(frame['members'])
            if len(members)!=len(frame['members']):
                continue
            frame_id=frame['receipt_sha256']; frame_at=frame['received_at']; quotes=[]; entries={}
            for entry in event['rows']:
                f=entry['facts']; dep='sgo-reference:'+entry['id']
                if (members.get(entry['id'])!=entry['revision'] or not inputs['dependencies'].get(dep)
                        or f.get('provider')!='sportsgameodds' or f.get('event_id')!=event_id
                        or f.get('league')!='NBA' or f.get('market')!='moneyline' or f.get('period')!='game'
                        or f.get('phase')!=('pregame' if phase=='scheduled' else 'live') or f.get('line') is not None
                        or f.get('available') is not True or f.get('side') not in ('home','away')
                        or (phase=='live' and (not f.get('source_at') or stamp(f['source_at'])<stamp(native['start_at'])))):
                    continue
                q={k:f.get(k) for k in ('provider','venue','event_id','odd_id','opposing_odd_id','league','market','period',
                    'phase','side','line','price_american','source_at','received_at','available')}
                q.update(frame_id=frame_id,frame_received_at=frame_at)
                quotes.append(q);entries[(q['venue'],q['odd_id'])]=(dep,inputs['dependencies'][dep])
            contract=dict(event_id=event_id,league='NBA',phase='pregame' if phase=='scheduled' else 'live',period='game',
                market='moneyline',side=side,line=None,settlement=SETTLEMENT,settlement_evidence=native_evidence,
                occurrence_evidence=occurrence_evidence,frame_id=frame_id,frame_received_at=frame_at)
            result,witness=reviewed_median(quotes,contract,at=inputs['captured_at'],evaluated_venue=row['venue'],registry=registry)
            if not result.get('available'):
                continue
            import json
            evidence=json.loads(witness.wire)['basis']['contributors']; deps=[]
            for contributor in evidence:
                for item in contributor['inputs']:
                    dep,revision=entries[(contributor['venue'],item['odd_id'])]
                    deps.append(dict(item,venue=contributor['venue'],dependency=dep,expected_revision=revision,state='available'))
            candidate=dict(witness=witness.wire,binding=dict(verified=True,row_id=row['id'],row_revision=row['quote_revision'],
                contract=contract,occurrence_evidence=occurrence_evidence,settlement_evidence=native_evidence),dependencies=deps)
            candidates.append((min(stamp(item['source_at']) for c in evidence for item in c['inputs']),result['probability'],candidate))
        if not candidates:return None
        latest=max(c[0] for c in candidates); winners=[c for c in candidates if c[0]==latest]
        if len({c[1] for c in winners})!=1:return None
        return sorted(winners,key=lambda c:c[2]['witness'])[0][2]
    except (KeyError,StopIteration,TypeError,ValueError,ArithmeticError,OSError):
        return None
