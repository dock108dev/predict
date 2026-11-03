"""Unit validation in an existing census transaction; never replaces raw census."""
from collections import Counter
from app.storage.result_publication import validate,invalid
from app.storage.latest_board import _control_barrier
from app.comparison.estimated_policy import load

def census(db,frame,owner,at,events,engine):
    frame['control_barrier']=_control_barrier(db);policy=load().revision
    rows=[];inventories={};reasons=Counter();financial=Counter();metrics=Counter()
    with db.cursor(name='result_census') as cursor:
        cursor.itersize=4
        cursor.execute('SELECT game_key,unit_id,generation_id,captured_at,calculated_at,published_at,facts FROM current_result_unit')
        for row in cursor:
            facts=row.pop('facts');dep=facts['publication_dependencies']
            if not set(dep['selector']['events'])&set(events):continue
            checks=validate(frame,facts,at=at.isoformat(),owner=owner,engine=engine,policy=policy)
            current=not invalid(checks);codes=sorted(set(checks['all']+[r for section in ('observations','comparisons') for values in checks[section].values() for r in values]))
            reasons.update(codes);financial[facts.get('estimate_availability',{}).get('state','unknown')]+=1
            row.update(current=current,reasons=codes,financial_state=facts.get('estimate_availability',{}).get('state'),events=dep['selector']['events'])
            rows.append(row)
            prior=inventories.get(row['game_key'])
            if prior is None or row['captured_at']>prior['at']:
                inventories[row['game_key']]=dict(at=row['captured_at'],units=facts.get('unit_inventory',[]))
            for kind,field in [('ev','buffered_ev_usd'),('arbs','buffered_complete_modeled_minimum_usd')]:
                for result in facts['boards'][kind]['rows']:
                    metrics[kind+'_retained_rows']+=1
                    numeric=(result.get('financial_metrics') or {}).get(field) is not None
                    metrics[kind+'_numeric_input_supported_rows']+=numeric
                    metrics[kind+'_numeric_dependency_current_rows']+=numeric and current
    for row in db.execute("SELECT game_key,facts->'result_unit_inventory' units,facts#>'{publication_dependencies,selector,events}' events FROM latest_board WHERE facts ? 'result_unit_inventory'"):
        if set(row['events'] or [])&set(events) and row['game_key'] not in inventories:inventories[row['game_key']]=dict(at=None,units=row['units'])
    from app.storage.result_inventory import current as inventory_current
    from app.storage.latest_board import runtime_identity
    discovered_events=set();unknown_events=set()
    for row in db.execute('SELECT game_key,discovered_at,events,dependencies,units,superseded_at,superseded_by FROM current_result_inventory'):
        members=set(row['events'])&set(events)
        if members:
            saved=row['dependencies']
            current=not row['superseded_at'] and inventory_current(frame,saved,engine=engine,policy=policy,owner=runtime_identity(owner),at=at.isoformat())
            inventories[row['game_key']]=dict(at=row['discovered_at'],units=row['units'],proof_current=current,superseded_at=row['superseded_at'],superseded_by=row['superseded_by'])
            (discovered_events if current else unknown_events).update(members)
    wanted={(game,u['id']) for game,inv in inventories.items() if not inv.get('superseded_at') for u in inv['units']}
    retained={(u['game_key'],u['unit_id']) for u in rows};current=sum(u['current'] for u in rows)
    return dict(known_unit_inventory=len(wanted),retained=len(rows),current=current,historical=len(rows)-current,
        superseded_inventories=[dict(game=game,at=inv['superseded_at'],successors=inv.get('superseded_by'),units=len(inv['units'])) for game,inv in inventories.items() if inv.get('superseded_at')],
        inventory_proof_current_events=len(discovered_events),unknown_inventory_event_ids=sorted(set(events)-discovered_events),
        obsolete_inventory_event_ids=sorted(unknown_events-discovered_events),
        retained_in_inventory=len(retained&wanted),retained_outside_inventory=len(retained-wanted),
        pending_known_units=len(wanted-retained),financial_states=dict(financial),reasons=dict(reasons),metrics=dict(metrics),records=rows,
        notes=['Currentness uses exactly the independently sealed unit dependency contract at the census snapshot.',
            'Unsupported is financial-input status, orthogonal to current/historical.',
            'Pending counts cover known inventories; missing undiscovered inventories are unknown, not successful.',
            'Legacy game-level financial-current fields in the surrounding census are not result-unit authority.'])
