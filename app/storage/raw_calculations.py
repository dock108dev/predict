"""Optional captured-result overlay. Never calculates or grants current authority."""
from app.dashboard.comparison_board import expand_price_fields,expand_odds


def matches(price,book,observation):
    source=price.get('source',{})
    if source.get('provider')=='the_odds_api':
        from app.dashboard.session_projection import stable
        market=book['market_id'].removeprefix('alternate_')
        native=stable([book['event_id'],market,str(observation['line']) if observation.get('line') is not None else None,observation['outcome_id']])
        if book.get('kind')=='alternate':native='alternate:'+native
        return (observation['side']=='offer' and source.get('quote_side')=='buy'
            and price.get('venue')==book['venue'] and source.get('provider')==book['provider']
            and source.get('native_event_id')==book['event_id'] and source.get('native_market_id')==native)
    return (observation['side']=='asks' and source.get('quote_side')=='buy'
        and price.get('original',{}).get('transformation')!='one_minus_native_bid'
        and price.get('venue')==book['venue'] and source.get('provider')==book['provider']
        and source.get('native_event_id')==book['event_id'] and source.get('native_market_id')==book['market_id']
        and source.get('native_outcome_id')==observation['outcome_id']
        and str(source.get('native_side','')).lower()==str(observation['native_side']).lower())


def read(db,book,observation,offset=0,limit=20):
    """Current compact publications, their own input frame and policy, paginated.

    A source-local association is not a proof of equivalent financial inputs.
    Even an identical selected price cannot establish peer/model currentness.
    Keep every result explicitly captured, including its original source prices.
    """
    row=db.execute("SELECT facts->'games' games FROM latest_board_status").fetchone()
    games=[g['game_key'] for g in (row or {}).get('games',[]) if [book['provider'],book['event_id']] in g.get('members',[])]
    results=[];count=0
    for key in games:
        for view in ('odds','ev','arbs'):
            row=db.execute("SELECT facts->'boards'->%s board FROM latest_board WHERE game_key=%s",(view,key)).fetchone()
            if not row or not row['board']:continue
            board=expand_odds(expand_price_fields(row['board']))
            prices={p['quote_id']:p for p in board.get('prices',[])}
            wanted={pid for pid,p in prices.items() if matches(p,book,observation)}
            if not wanted:continue
            candidates=([dict(p['gross_comparison'],quote_id=p['quote_id']) for p in prices.values()
                if p['quote_id'] in wanted and p.get('gross_comparison',{}).get('available')]
                if view=='odds' else board.get('rows',[]))
            for result in candidates:
                ids={result.get('quote_id'),result.get('price_ref')}
                ids.update(l.get('quote_id') or l.get('price_ref') for l in result.get('legs',[]))
                if not ids & wanted:continue
                if offset<=count<offset+limit:
                    inputs=result['inputs'] if view=='odds' else [prices[pid] for pid in sorted(ids-{None}) if pid in prices]
                    results.append(dict(state='captured_result',view=view,game_key=key,
                        calculated_at=board.get('calculated_at'),calculation_context=board.get('calculation_context'),
                        policy=board.get('policy'),captured_inputs=inputs,result=result,
                        raw_revision=book['revision'],current_eligibility=False,
                        association='Exact native identity only; captured prices, clocks, depth and calculation basis govern this result'))
                count+=1
    return dict(state='captured_result' if count else 'unavailable',results=results,total=count,
        next_offset=offset+limit if offset+limit<count else None,provider_requests=0)
