"""Bounded selected evidence carried by the ordinary immutable read frame."""
import json
from types import SimpleNamespace

from .store import encoded, stamp, hashed
from .payload_codec import encode, decode


def proof(frame, selector):
    from . import observation_publication as publication
    neighbors=publication.neighborhood(frame,selector)
    ids={row[0] for row in neighbors}
    return hashed([neighbors,sorted((cid,publication.own(frame,cid),row['received_at'])
        for cid,row in frame['offers'].items() if row['event_id'] in ids)])


def pack(observed, financial, context, dependencies):
    def bundle(value):
        if value is None:return None
        return {key:value[key] for key in ('game_key','input_version','as_of','state_inputs','benchmark_venue','representation','benchmark','benchmark_reason') if key in value}
    return encode(encoded(dict(observed=bundle(observed),financial=bundle(financial),
        at=context.at,epoch=context.epoch,engine=context.engine,
        proof=proof(context.publication_frame,dependencies['selector']))).decode())


def bind_token(board, token):
    # Price dictionaries are encoded separately; selection identities in rows
    # and decoded prices must survive lossless compaction.
    from app.dashboard.comparison_board import expand_price_fields, expand_odds, compact_odds, compact_price_fields
    expanded=expand_odds(expand_price_fields(board))
    for row in expanded.get('prices',[]):
        if row.get('inputs_identity'):row['inputs_identity']['read_token']=token
    for row in expanded.get('rows',[]):
        if row.get('details'):row['details']['read_token']=token
    compact_price_fields(compact_odds(expanded))


def read(db, saved, query, policy, *, stopped=False, guard=lambda _:None):
    from .latest_board import runtime, source_states
    from .current_games import utc, engine_binding
    from . import observation_publication as publication
    from .comparison_board import calculate_current
    from app.comparison.estimated_policy import load
    from app.dashboard.comparison_board import details, entries, quote_key, price, age_observation, benchmark
    facts=saved['facts'];identity=query['context_id']
    observation=identity==(facts.get('observation_context') or {}).get('context_id')
    expected=facts.get('observation_context') if observation else facts.get('context')
    if expected is None or expected['context_id']!=identity:raise ValueError('current_inputs_changed_or_removed')
    payload=facts.get('selected_frame')
    if payload is None:raise ValueError('current_slate_read_expired')
    text=decode(payload);guard(len(text)*8)
    captured=json.loads(text);context=SimpleNamespace(**{k:captured[k] for k in ('at','epoch','engine')})
    bundle=captured['observed' if observation else 'financial']
    if bundle is None or bundle['game_key']!=query['game']:raise ValueError('current_inputs_changed_or_removed')
    owner=runtime(db);now=utc()
    committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
    states=source_states(committed,owner)
    dependency=facts['publication_dependencies']
    frame=publication.capture(db,states,selector=dependency['selector'],compact=True,resource_guard=guard)
    if frame['epoch']!=context.epoch:raise ValueError('current_inputs_changed_or_removed')
    checks=publication.reasons(frame,dependency)
    changed=bool(checks['all'] or any(checks['observations'].values()) or any(checks['comparisons'].values())
        or (not observation and captured['proof']!=proof(frame,dependency['selector']))
        or context.engine!=engine_binding() or (not observation and expected['policy_revision']!=load().revision)
        or stopped or not owner.get('active') or not owner.get('healthy'))
    bundle['calculation_context']=expected
    if query['view']=='inputs':
        selected=next(((e,g,q) for e,g,q in entries(bundle['state_inputs']) if quote_key(q)==query.get('quote')),None)
        if selected is None:raise ValueError('current_selection_removed')
        event,group,q=selected
        observed=age_observation(price(q),event,stamp(now),source_states=states,
            publication_reasons=['current_dependencies_changed'] if changed else [])
        out=dict(version='predict-board-inputs-2',game_key=bundle['game_key'],quote_id=query['quote'],
            quote_revision=observed['quote_revision'],observation_revision=observed['observation_revision'],calculation_context=expected,
            evidence=dict(event=event['title'],event_metadata={k:event[k] for k in ('sport','league','title','start_at','participants')},
                market={k:group[k] for k in ('market','period','period_boundary','line','anchor_participant')},selection=q['binding']['selection'],
                source=q['source'],original=q['original'],times=q['times'],native_contract=q.get('native_contract'),
                book_confirmation=q.get('book_confirmation'),provenance=q.get('provenance'),depth=observed['observed_depth']['levels'],
                observed_depth=observed['observed_depth'],provider_clocks=q.get('provider_clocks'),source_state=observed['source_state'],
                quote_revision=q['revision'],observation_revision=observed['observation_revision'],
                freshness=observed['freshness'],observation_display=observed['observation_display'],
                source_health=observed['source_health'],estimate_availability=facts.get('estimate_availability'),
                benchmark=benchmark(bundle,context.at),benchmark_reason=bundle.get('benchmark_reason'),representation=bundle['representation']),provider_requests=0)
    else:
        if observation:raise ValueError('estimate_unavailable')
        if policy.benchmark_venue!=bundle['benchmark_venue']:raise ValueError('current_inputs_changed_or_removed')
        value=calculate_current(bundle,policy,context=context,details=True,selected_quote=query.get('quote'),selected_pair=query.get('pair'))
        out=details(value,quote=query.get('quote'),pair=query.get('pair'),at=now,current=bundle['state_inputs'],history=changed,stopped=stopped)
        out['captured_calculated_at']=saved.get('calculated_at')
        out['selection_context']=expected
        out['original_inputs_identity'].update(context_id=identity,policy_revision=expected['policy_revision'],read_token=query.get('read_token'))
        selected_quotes=[out['quote']] if out['quote'] else out['leg_quotes']
        events={quote_key(q):event for event,_,q in entries(bundle['state_inputs'])}
        for q in selected_quotes:
            observed=age_observation(price(q),events[quote_key(q)],stamp(now),source_states=states,
                publication_reasons=['current_dependencies_changed'] if changed else [])
            for field in ('source_state','source_health','observation_display'):q[field]=observed[field]
    out['selection_status']='captured' if changed else 'unchanged'
    out['read_token']=query.get('read_token')
    if len(encoded(out))>8*1024*1024:raise ValueError('board_response_byte_capacity')
    return out
