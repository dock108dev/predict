"""Same-outcome presentation over shared contracts. No implied settlement equivalence."""
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote
from app.opportunities.board import contracts
from app.dashboard.session_projection import stable
from app.depth import consume
from app.fees import calculate


def seconds(a, b):
    if not a or not b:return None
    return str(Decimal(str((datetime.fromisoformat(a.replace('Z','+00:00'))-datetime.fromisoformat(b.replace('Z','+00:00'))).total_seconds())))


def entry_cost(contract, quantity, at, identity, source):
    """Provisional entry only; material settlement/private costs are never zeroed."""
    result=dict(lower=None,upper=None,net=None,quantity=str(quantity),
        basis='Provisional entry cost only; settlement/private charges unknown. Not net return.')
    if not contract['levels'] or contract['top_size'] is None:return result
    try:
        fills=consume(contract['levels'],str(quantity))
        c=dict(venue=contract['venue'],environment='production',market_id=source['market_id'],product='event_contract',
            trade_time=at,calculation_time=at,complete_order_history=True,settlement_status='UNKNOWN',outcomes={},
            fills=[dict(fill_id=str(i),order_id='new-taker-order',role='taker',price=f['price'],quantity=f['quantity'],unit='contracts') for i,f in enumerate(fills)])
        if contract['venue']=='polymarket_us':
            if datetime.fromisoformat(at.replace('Z','+00:00'))<datetime.fromisoformat('2026-09-17T04:00:00+00:00'):return result
            from app.fees.entry_bounds import us_taker_bound
            bound=us_taker_bound(fills)
            notional=sum(Decimal(f['price'])*Decimal(f['quantity']) for f in fills)
            result.update(lower=str(notional),upper=str(notional+Decimal(bound['upper'])),audit=bound,
                basis=result['basis']+' US standard taker theta 0.0695; unknown fill allocation gives a commission range.')
        elif identity['competition']=='NFL' and identity['family']=='moneyline' and identity['period']=='full_game':
            c.update(schedule_version='kalshi-july7-observed-sep12',series_id='KXNFLGAME',event_id=source['event_id'],balance_precision='0.01',
                kalshi_metadata=dict(source='Owner provisionally accepted retained NFL schedule; hypothetical new taker order, cent balance, no event override',
                    series_id='KXNFLGAME',event_id=source['event_id'],event_history_complete=False,
                    series_changes=[dict(scheduled_ts=at,fee_type='quadratic_with_maker_fees',fee_multiplier='1')],event_changes=[]))
            audit=calculate(c);cost=audit['entry_cash_requirement']
            result.update(lower=cost,upper=cost,audit=audit)
    except (ValueError,KeyError,ArithmeticError):pass
    return result


def market_url(snapshot, venue, native):
    if snapshot['data_mode']=='synthetic':return None
    if venue=='polymarket_us':
        # Event routes require the retained event slug, not the market's slug.
        events=[e for source in snapshot.get('sources',[]) if source['source_id']==venue
            for e in (source.get('catalog') or {}).get('events',[])
            if e['id']==native.get('event_id')]
        if len(events)!=1:return None
        event=events[0]
        slug=(event.get('native_aliases') or {}).get('slug')
        metadata_slug=(event.get('native_metadata') or {}).get('slug')
        if not slug or (metadata_slug and metadata_slug!=slug):return None
        return 'https://polymarket.us/event/'+quote(slug,safe='')
    if venue=='kalshi':
        # Canonical market lookup route uses the exact native ticker.
        return 'https://kalshi.com/markets/'+quote(native['event_id'].split('-')[0].lower(),safe='')+'/pro-football/'+quote(native['event_id'].lower(),safe='')+'?market='+quote(native['id'],safe='')
    return None


def comparisons(snapshot, query):
    rows=[]
    for game in snapshot['games']:
        if set(game['sources'])!={'kalshi','polymarket_us'}:continue
        ident=game['product_identity']
        if any(query.get(k) and ident.get(k)!=query[k] for k in ('competition','season','period','family')):continue
        if query.get('search','').lower() not in game['title'].lower():continue
        if query.get('venue') and not all(v in game['sources'] for v in query['venue'].split('+')):continue
        point=snapshot['points'][game['id']];cs=contracts(point,game);groups={}
        from app.opportunities.board import assess
        from app.settlement import compare_profiles
        profiles={}
        for metadata in snapshot['rows_by_game'][game['id']]:
            try:profiles.update(assess([metadata],point['at'],game)['profiles'])
            except (ValueError,KeyError,StopIteration):pass
        settlement_audit=compare_profiles(profiles['kalshi'],profiles['polymarket_us']) if set(profiles)=={'kalshi','polymarket_us'} else None
        settlement_status=settlement_audit['status'] if settlement_audit else 'UNKNOWN'

        for key,side in game['sides'].items():
            # Complement maps only a two-team winner; retain the native predicate in Details.
            if side['predicate']=='not_win' and ident['family']=='moneyline' and len(game['teams'])==2:
                outcome=next(t for t in game['teams'] if t!=side['participant'])
            elif side['predicate']=='win':outcome=side['participant']
            else:outcome=stable(side)
            groups.setdefault(outcome,[]).append(key)
        for outcome,keys in sorted(groups.items()):
            if len(keys)!=2 or {cs[k]['venue'] for k in keys}!={'kalshi','polymarket_us'}:continue
            legs=[]
            for key in sorted(keys):
                c=cs[key];venue=c['venue'];card=next(ca for ca in point['cards'] if ca['venue']==venue)
                native=next(m['native'] for m in snapshot['market_catalog'] if m['source_id']==venue and m['market_id']==game['sources'][venue]['market_id'])
                book=card['book'] or {}
                age=c['age_seconds'];recent=age is not None and 0<=Decimal(age)<=15
                legs.append(dict(c,native_identity=game['sources'][venue],native_outcome=game['sides'][key],url=market_url(snapshot,venue,native),
                    local_timing=book.get('local_timing'),application_received_at=book.get('application_received_at'),status='recent receipt' if recent and c['connection']=='connected' and book.get('sync')=='synchronized' else 'stale or unavailable',
                    market_state=book.get('market_state','unknown'),source_age_seconds=seconds(point['at'],c['source_at']),source_to_receipt_seconds=seconds(c['received_at'],c['source_at']),
                    depth_limit='Advertised top levels only; not total exchange depth' if venue=='polymarket_us' else 'Retained snapshot/delta bid book; buy prices complement opposite bids',
                    entry=entry_cost(c,Decimal(query.get('quantity','100')),point['at'],ident,game['sources'][venue])))
            prices=[Decimal(l['ask']) if l['ask'] is not None else None for l in legs]
            gap=None if None in prices else abs(prices[0]-prices[1])
            lower=None if gap is None else 'Equal' if gap==0 else legs[prices.index(min(prices))]['label']
            skew=seconds(legs[0]['received_at'],legs[1]['received_at'])
            # Unknown source clock/state intervals cannot establish synchronized freshness.
            timing=dict(receipt_skew_seconds=None if skew is None else str(abs(Decimal(skew))),
                receipt_limits_pass=all(l['status']=='recent receipt' for l in legs) and skew is not None and abs(Decimal(skew))<=5,
                synchronized=False,reason='Source clock uncertainty and continuous market-state validity unverified; 15s age / 5s alignment ceilings retained')
            entry_lower=None
            if all(l['entry']['upper'] is not None for l in legs):
                if Decimal(legs[0]['entry']['upper'])<Decimal(legs[1]['entry']['lower']):entry_lower=legs[0]['label']
                elif Decimal(legs[1]['entry']['upper'])<Decimal(legs[0]['entry']['lower']):entry_lower=legs[1]['label']
            rows.append(dict(id='comparison-'+stable([game['id'],outcome]),game_id=game['id'],game_title=game['title'],outcome=outcome,identity=ident,
                session=snapshot['session_id']+'~'+game['id'],hash=snapshot['session_id'],cutoff=point['id'],at=point['at'],
                contract=keys[0],candidate='',legs=legs,lower_raw=lower,raw_difference=None if gap is None else str(gap),
                entry_lower=entry_lower,timing=timing,settlement_audit=settlement_audit,settlement_status=settlement_status,settlement=settlement_status+': matching event/outcome alone does not establish equivalent settlement; native exceptions remain material',
                net=None,ev=None,mode=snapshot['data_mode'],historical=snapshot['view_mode']!='current'))
    return group_comparisons(rows)


def comparison_order(row):
    """Largest exact raw gap first; unknown gaps last, with stable tie ordering."""
    gap=row['raw_difference']
    return (gap is None,-Decimal(gap) if gap is not None else Decimal(0),
            row['identity']['scheduled_start'] or '',row['game_title'],row['outcome'],row['id'])


def group_comparisons(rows):
    """One outcome card; retain distinct native predicates as explicit alternatives."""
    groups={}
    for row in rows:
        key=stable([row['identity'],row['outcome'],sorted((l['venue'],l['native_identity']['event_id']) for l in row['legs'])])
        groups.setdefault(key,[]).append(row)
    result=[]
    for key,choices in groups.items():
        # Prefer the direct winner predicate. Never silently treat opposing NO as
        # identical settlement or combine its liquidity with the YES contract.
        choices.sort(key=lambda r:(sum(l['native_outcome']['predicate']!='win' for l in r['legs']),r['id']))
        primary=dict(choices[0],id='comparison-'+key,alternatives=choices[1:],event_key=stable(choices[0]['identity']['event']))
        result.append(primary)
    return sorted(result,key=comparison_order)
