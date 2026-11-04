"""Finite local capture -> match -> math -> atomic replacement, independent of queues."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction as F
import gzip
import lzma
import json
from time import monotonic
from uuid import uuid4
from psycopg.types.json import Jsonb

from .store import Store, encoded, hashed, stamp
from .current_games import utc
from .current_rows import CurrentRowStore
from .comparison_board import ReadContext
from app.comparison.snapshot_math import assumptions, funded
from app.comparison.cashflows import exact_wire as wire

SPORTS=('NFL','NCAAF','NBA','NCAAB','MLB','NHL')


class SnapshotOperationError(ValueError):
    """An expected snapshot refusal that can be shown to the caller."""


def pack(value):
    content=lzma.compress(encoded(value),preset=1)
    if len(content)>96*1024*1024:raise SnapshotOperationError('Snapshot storage capacity reached')
    return content


def unpack(value):
    decompress=gzip.decompress if value.startswith(b"\x1f\x8b") else lzma.decompress
    return json.loads(decompress(value))


def neighborhoods(frame):
    """Necessary-condition components; no possible occurrence peer is omitted.

    The resolver can compare records sharing source event, participant set or a
    typed provider ID. Union those indexes before invoking its exact predicates.
    This bounds normalization per match neighborhood without altering matching.
    """
    from app.comparison.occurrence_matching import OccurrenceResolver
    resolver=OccurrenceResolver();parents={};records={}
    def root(k):
        parents.setdefault(k,k)
        while parents[k]!=k:
            parents[k]=parents[parents[k]];k=parents[k]
        return k
    for r in frame['records']:
        f=resolver._facts(r)
        keys=[('event',*f['key']),('roles',f['league'],*sorted(f['roles'].values())),
              *(('shared',name,value) for name,value in f['shared'].items())]
        first=root(keys[0])
        for k in keys[1:]:parents[root(k)]=first
        records.setdefault(keys[0],[]).append(r)
    groups={}
    for k,rows in records.items():groups.setdefault(root(k),[]).extend(rows)
    for rows in groups.values():yield dict(frame,records=rows)


def capture(db, *, at=None):
    from app.dashboard.comparison_board import entries, price
    from app.dashboard.current_contract import identity
    from app.comparison.same_outcome import quote_identity
    from app.dashboard.grouped_odds import reference_prices
    at=at or utc();start=monotonic();out=dict(captured_at=at,quotes=[],references=[],games=[],sources={},issues=[])
    # All leagues share one MVCC transaction. Per-league materialization avoids
    # duplicating the complete normalized universe in the old board cache.
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        db.execute('SET LOCAL statement_timeout=30000')
        for league in SPORTS:
            ids=[r['id'] for r in db.execute('''SELECT id FROM current_event WHERE facts->>'competition'=%s
                AND scheduled_start::timestamptz >= %s AND scheduled_start::timestamptz < %s''',
                (league,stamp(at),stamp(at)+timedelta(hours=72))).fetchall()]
            if not ids:continue
            frame=CurrentRowStore(db).capture(include_depth=False,event_ids=ids)
            # Hydrate only the captured contracts, still inside this MVCC frame.
            frame['records']=CurrentRowStore(db).hydrate_records(frame['records'])
            # Preserve full reference witnesses before strict execution/catalog
            # filters. A display price alone cannot prove a benchmark pair.
            captured_refs=reference_prices(frame['records'])
            records_by_source={hashed(r['quote']['source']):r for r in frame['records'] if r['quote']['venue']=='pinnacle'}
            for ref in captured_refs:
                ref['original_record']=deepcopy(records_by_source[ref['id']])
                ref['game_key']='reference:'+hashed([ref['source']['provider'],ref['source']['native_event_id']])
            out['references'].extend(captured_refs)
            out['sources'].update(frame['source_status'])
            for neighborhood in neighborhoods(frame):
                context=ReadContext(Store(None),at=at,frame=neighborhood,tolerate_invalid_catalog=True)
                for catalog in context.catalog_bundles():
                    if monotonic()-start>120:raise SnapshotOperationError('Snapshot capture exceeded two minutes; prior result retained')
                    try:bundle=context.observation_bundles(game=catalog['game_key'])[0]
                    except (ValueError,KeyError,TypeError) as exc:
                        out['issues'].append(dict(game=catalog['game_key'],reason=str(exc)[:180]));continue
                    game=dict(catalog['catalog_event'],game_key=catalog['game_key'])
                    out['games'].append(game)
                    records={hashed(r['quote']['source']):r for r in bundle['records']}
                    refs=reference_prices(bundle['records'])
                    for ref in refs:ref['game_key']=game['game_key']
                    reference_games={r['id']:r['game_key'] for r in refs}
                    for ref in captured_refs:
                        if ref['id'] in reference_games:ref['game_key']=reference_games[ref['id']]
                    for event,group,q in entries(bundle['state_inputs']):
                        record=records[hashed(q['source'])]
                        row=price(q)
                        row.update(game_key=game['game_key'],game_title=game['title'],league=league,
                            start_at=game['start_at'],market={k:group.get(k) for k in ('market','period','line')},
                            same_outcome=quote_identity(q,group,event),
                            original_record=record,native_contract=q.get('native_contract'),binding=q['binding'])
                        # Observation construction intentionally strips finance. Restore
                        # only the exact reference from this same captured record.
                        reference=deepcopy(record['quote'].get('sharp_reference'))
                        if reference:
                            reference['selection_digest']=identity('binding',q['binding']['selection'])
                        row['reference']=reference
                        row['benchmark_quote']=dict(q,sharp_reference=reference) if reference else None
                        row['id']=hashed([game['game_key'],row['quote_id']])
                        out['quotes'].append(row)
                out['issues'].extend(context.catalog_errors)
        out['epoch']=str(db.execute('SELECT epoch FROM current_row_epoch WHERE singleton').fetchone()['epoch'])
        out['sources']={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
    out['id']=uuid4().hex
    out['capture_seconds']=round(monotonic()-start,3)
    return out


def probability(row,settings,at):
    from app.collection.current_benchmark import calculate,validate_reference
    if row['league']=='NCAAB':
        ref=row.get('snapshot_benchmark')
        return (ref['probability'],None) if ref else (None,row.get('snapshot_benchmark_missing','Exact two-sided Pinnacle reference unavailable'))
    q=row.get('benchmark_quote')
    if not q:return None,'Exact two-sided '+settings['benchmark_venue'].title()+' reference unavailable'
    try:
        validate_reference(q['sharp_reference'],q['binding']['selection'],venue=settings['benchmark_venue'])
        value=calculate(q,stamp(at),allow_last_known=True)
        if value.get('value') is None:return None,value.get('reason')
        p=value['basis']['probability']
        return wire(F(int(p['numerator']),int(p['denominator']))),None
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:return None,str(exc)


def calculate(inputs,value=None):
    from app.dashboard.current_contract import price
    settings,policy=assumptions(value)
    rows=[];pairs=[];oppositions={}
    from app.comparison.snapshot_benchmark import bind
    from app.comparison import snapshot_named_benchmark as named
    benchmark_refs=named.references(inputs['quotes'],inputs['references'],settings)
    named_quotes=named.bind(inputs['quotes'],benchmark_refs,settings)
    projected,benchmark_diagnostics=bind(named_quotes,benchmark_refs,settings,inputs['captured_at'])
    game_keys={old['game_key']:new['game_key'] for old,new in zip(inputs['quotes'],projected)}
    from app.comparison.snapshot_identity import games as projected_games
    games=projected_games(inputs,projected)
    references=[dict(r,game_key=game_keys.get(r.get('game_key'),r.get('game_key'))) for r in inputs['references']]
    for original in projected:
        row={k:v for k,v in original.items() if k not in ('benchmark_quote','original_record','native_contract')}
        row['game_title']=games.get(row['game_key'],{}).get('title',row['game_title'])
        record=original.get('original_record') or {}
        participant=record.get('selection',{}).get('participant')
        row['participant_label']=next((name for name,pid in record.get('event',{}).get('participants',{}).items() if pid==participant),None)
        row['probability'],row['probability_missing']=probability(original,settings,inputs['captured_at'])
        supported=row['common_odds'].get('supported') and (row['snapshot_supported'] if 'snapshot_supported' in row else row['binding'].get('verified'))
        cost=price(original) if supported else None
        if cost is not None and cost<=0:cost=None
        row['cost_per_normal_claim']=wire(cost)
        p=None if row['probability'] is None else F(row['probability'])
        row['gross_return_percent']=None if p is None or cost is None else wire(100*(p/cost-1))
        row['math']=dict(available=False,missing=['supported price and selection']) if cost is None else funded([cost],[p],[row['venue']],settings,policy)
        row['net_return_percent']=row['math'].get('buffered_return_percent')
        row['input_basis']=dict(price='observed captured original',probability='unavailable' if p is None else 'configured proportional no-vig decisive benchmark; not an observed probability',fees='unavailable' if settings['fees'][row['venue']] is None else 'configured hypothetical upfront rate',scenario='unavailable' if settings['scenario']=='unavailable' else 'configured hypothetical settlement scenario',sizing='unavailable' if settings['sizing']=='unavailable' else 'configured fractional top-price size; observed depth not used',buffer='configured once on deployed capital')
        row['gross_profit_per_claim']=None if p is None or cost is None else wire(p-cost)
        from app.comparison.conditional_benchmark import snapshot_metric
        row['conditional_trade_benchmark']=snapshot_metric(row,at=inputs['captured_at'])
        row['conditional_return_percent']=row['conditional_trade_benchmark'].get('return_percent')
        from app.dashboard.u0_display import quote_display
        ref=original.get('reference')
        row['reference_odds']=None if not ref else dict(quote_display(ref['selected_odds'],'decimal_odds'),source_at=ref['source_at'],role='reference_only')
        if row['reference_odds']:row['reference_odds'].pop('what_if',None)
        row['kind']='single';rows.append(row)
        # Conditional opposing scenarios require supported exact identity and
        # the same occurrence, scoring, domain and exact threshold. NO/Short
        # keep their own explicit predicates; never infer opponent by label.
        contract=original.get('native_contract') or {};facts=contract.get('same_outcome') or {}
        pred=facts.get('predicate')
        op = pred.get('operator') if pred else None
        if row.get('snapshot_identity') and pred and F(pred['threshold']).denominator!=1:op={'ge':'gt','le':'lt'}.get(op,op)
        if cost is not None and row['same_outcome']['supported'] and pred and op in ('gt','lt'):
            key=hashed([row['game_key'],row['market']['market'],row['market']['period'],facts.get('scoring') or contract.get('scope'),pred['domain'],pred.get('subject_id'),str(F(pred['threshold']))])
            oppositions.setdefault(key,{}).setdefault(op,[]).append(row)
    for sides in oppositions.values():
        for a in sides.get('gt',[]):
            for b in sides.get('lt',[]):
                if a['id']==b['id'] or a['venue']==b['venue'] and not (a.get('snapshot_identity') and b.get('snapshot_identity')):continue
                m=funded([a['cost_per_normal_claim'],b['cost_per_normal_claim']],[a['probability']],[a['venue'],b['venue']],settings,policy)
                pairs.append(dict(id=hashed([a['id'],b['id']]),kind='pair',game_key=a['game_key'],game_title=a['game_title'],league=a['league'],start_at=a['start_at'],market=a['market'],legs=[a['id'],b['id']],venues=[a['venue'],b['venue']],math=m,
                    minimum_return_percent=m.get('scenario_minimum_percent'),
                    snapshot_identities=[a.get('snapshot_identity'),b.get('snapshot_identity')]))
    groups={}
    for row in rows:
        ident=row['same_outcome']
        key=hashed([row['game_key'],ident['key']]) if ident['supported'] else row['id']
        groups.setdefault(key,[]).append(row)
    for peers in groups.values():
        for row in peers:
            choices=[F(p['cost_per_normal_claim']) for p in peers if p['id']!=row['id'] and (p['venue']!=row['venue'] or row.get('snapshot_identity')) and p['cost_per_normal_claim'] is not None]
            row['price_difference_cents']=None if not choices or row['cost_per_normal_claim'] is None else wire(100*(min(choices)-F(row['cost_per_normal_claim'])))
    return dict(id=uuid4().hex,snapshot_id=inputs['id'],captured_at=inputs['captured_at'],assumptions=settings,
        calculated_at=utc(),rows=rows,pairs=pairs,games=list(games.values()),references=references,sources=inputs['sources'],issues=inputs['issues'],
        counts=dict(observations=len(rows),gross_numeric=sum(r['gross_return_percent'] is not None for r in rows),
            conditional_numeric=sum(r['conditional_return_percent'] is not None for r in rows),
            net_numeric=sum(r['net_return_percent'] is not None for r in rows),pairs=len(pairs),
            unmatched=sum(not r['same_outcome']['supported'] for r in rows)),provider_requests=0,
        capture_seconds=inputs['capture_seconds'],benchmark_diagnostics=benchmark_diagnostics,
        scope=dict(leagues=list(SPORTS),families=['winner','spread','total'],period='full_game',horizon_hours=72),
        live_eligibility='not assessed; captured math does not establish current source availability or executable size')


def current(db,result_id=None):
    with db.transaction():
        row=db.execute("""UPDATE comparison_snapshot_result SET lease_until=now()+interval '2 hours'
            WHERE id=COALESCE(%s,(SELECT result_id FROM comparison_snapshot_head))
            RETURNING snapshot_id,result""",(result_id,)).fetchone()
        if row is None:return None
        db.execute("UPDATE comparison_snapshot SET lease_until=now()+interval '2 hours' WHERE id=%s",(row['snapshot_id'],))
    return unpack(row['result'])


def prune(db):
    """Serialize with capture, and skip a result whose reader is renewing its lease."""
    with db.transaction():
        if not db.execute('SELECT pg_try_advisory_xact_lock(901153) held').fetchone()['held']:
            return
        db.execute('''WITH newest AS (SELECT id FROM comparison_snapshot ORDER BY captured_at DESC,id DESC LIMIT 2),
            keep_latest AS (SELECT DISTINCT ON (r.snapshot_id) r.id FROM comparison_snapshot_result r
                JOIN comparison_snapshot s ON s.id=r.snapshot_id
                WHERE s.id IN (SELECT id FROM newest) OR s.lease_until>=now()
                ORDER BY r.snapshot_id,r.calculated_at DESC,r.id DESC)
            DELETE FROM comparison_snapshot_result WHERE id IN (
                SELECT id FROM comparison_snapshot_result WHERE lease_until<now()
                AND id NOT IN (SELECT result_id FROM comparison_snapshot_head)
                AND id NOT IN (SELECT result_id FROM comparison_snapshot_review)
                AND id NOT IN (SELECT id FROM keep_latest) FOR UPDATE SKIP LOCKED)''')
        db.execute('''DELETE FROM comparison_snapshot WHERE lease_until<now()
            AND id NOT IN (SELECT snapshot_id FROM comparison_snapshot_result)
            AND id NOT IN (SELECT id FROM comparison_snapshot ORDER BY captured_at DESC,id DESC LIMIT 2)''')


def replace(db, *, action, value=None, expected=None):
    # Session lock serializes finite operations across HTTP workers. Readers
    # continue seeing the prior committed head until this one atomically lands.
    if not db.execute('SELECT pg_try_advisory_lock(901153) locked').fetchone()['locked']:
        raise SnapshotOperationError('Another snapshot operation is running; previous result retained')
    try:
        prior=current(db)
        if expected is not None and (prior is None or prior['id']!=expected):raise SnapshotOperationError('Snapshot changed; reload before applying settings')
        if action=='recalculate':
            if prior is None:raise SnapshotOperationError('Capture prices before recalculating')
            inputs=unpack(db.execute('SELECT inputs FROM comparison_snapshot WHERE id=%s',(prior['snapshot_id'],)).fetchone()['inputs'])
        elif action=='refresh':inputs=capture(db)
        else:raise SnapshotOperationError('Unknown snapshot operation')
        result=calculate(inputs,value if value is not None else prior['assumptions'] if prior else None)
        packed_inputs=pack(inputs) if action=='refresh' else b''
        packed_result=pack(result)
        from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage
        from .storage_maintenance import REWRITE_RUNWAY_BYTES
        # TOAST chunks, indexes and ordinary concurrent ingestion need runway.
        estimated_write=(len(packed_inputs)+len(packed_result))*2
        if sql_usage(db)+estimated_write+REWRITE_RUNWAY_BYTES>=SQL_BYTE_CAP:
            raise SnapshotOperationError('Insufficient SQL headroom for snapshot; previous result retained')
        with db.transaction():
            if action=='refresh':db.execute('INSERT INTO comparison_snapshot(id,captured_at,inputs) VALUES (%s,%s,%s)',(inputs['id'],inputs['captured_at'],packed_inputs))
            db.execute('INSERT INTO comparison_snapshot_result(id,snapshot_id,assumptions,result) VALUES (%s,%s,%s,%s)',(result['id'],inputs['id'],Jsonb(result['assumptions']),packed_result))
            db.execute('INSERT INTO comparison_snapshot_head(singleton,result_id) VALUES (true,%s) ON CONFLICT(singleton) DO UPDATE SET result_id=EXCLUDED.result_id',(result['id'],))
            prune(db)
        return result
    finally:db.execute('SELECT pg_advisory_unlock(901153)')
