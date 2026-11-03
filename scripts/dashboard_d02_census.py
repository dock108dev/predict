"""Read-only, one-snapshot 72-hour metric census. Reasons overlap within units."""
import json
from collections import Counter, defaultdict
from datetime import timedelta, timezone
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect, stamp
from app.storage.payload_codec import decode
from app.storage.shared_json import loads
from app.dashboard.comparison_board import expand_price_fields, expand_odds, entries
from app.comparison.current_dependencies import eligibility
from app.storage.current_games import engine_binding


def run(destination):
    cohorts=defaultdict(Counter); reasons=defaultdict(Counter); searches=Counter(); games=0; refreshed=0
    with connect() as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        at=db.execute('select transaction_timestamp() at').fetchone()['at'].astimezone(timezone.utc);end=at+timedelta(hours=72)
        status=db.execute('select facts from latest_board_status').fetchone()['facts']
        catalog={g['game_key']:g for g in status['games'] if g.get('start_at') and at<=stamp(g['start_at'])<end}
        engine=engine_binding()
        with db.cursor(name='d02_metric_census') as cursor:
            cursor.itersize=1;cursor.execute('select game_key,facts from latest_board where game_key=ANY(%s)',(list(catalog),))
            for saved in cursor:
                games+=1;f=saved['facts'];refreshed+=f.get('context',{}).get('engine_binding')==engine
                packed=f.get('selected_frame')
                financial=loads(decode(packed)).get('financial') if packed else None
                index={q['id']:(event['league'],{'winner':'moneyline'}.get(group['market'],group['market']))
                    for event,group,q in entries(financial['state_inputs'])} if financial else {}
                odds=expand_odds(expand_price_fields(f['boards']['odds']))
                index.update({p['quote_id']:(p['event']['league'],{'winner':'moneyline'}.get(p['market']['market'],p['market']['market']))
                    for p in odds['prices']})
                ev=expand_price_fields(f['boards']['ev']); prices={p['quote_id']:p for p in ev['prices']}
                for row in ev['rows']:
                    p=prices[row.get('price_ref') or row['quote_id']]
                    fallback=(catalog[saved['game_key']]['league'],{'win':'moneyline','not_win':'moneyline','draw':'moneyline','cover':'spread','over':'total','under':'total'}.get(p['selection']['predicate'],'unknown'))
                    key='|'.join((p['venue'],*index.get(row['quote_id'],fallback)))
                    c=cohorts[key];c['ev_rows']+=1
                    metric=row.get('financial_metrics',{});c['full_state_ev_numeric_retained']+=metric.get('buffered_ev_usd') is not None
                    reason=set(row.get('availability',{}).get('metrics',{}).get('buffered_ev_usd',{}).get('reason_codes',[]))
                    reasons[key+'|ev'].update(reason)
                    conditional=row.get('conditional_trade_benchmark',{})
                    if conditional.get('available'):
                        c['conditional_numeric_retained']+=1
                        if conditional['evidence']['version'].endswith('20261030-review-3'):c['conditional_new_review_retained']+=1
                arb=expand_price_fields(f['boards']['arbs']);searches['pair_rows']+=len(arb['rows'])
                searches['input_search_refusal_units']+=max(0,arb['availability']['total_results']-len(arb['rows']))
                if financial:
                    state=financial['state_inputs'];seen=set()
                    for event,group,q in entries(state):
                        if q['id'] in seen:continue
                        seen.add(q['id']);key='|'.join((q['venue'],event['league'],{'winner':'moneyline'}.get(group['market'],group['market'])))
                        c=cohorts[key];c['strict_pair_candidate_legs']+=1
                        why=set(eligibility(q,state['comparison_profiles'],at,kinds=('identity','payout','fee','quantity','buffer')))
                        if why:c['strict_pair_blocked_legs']+=1
                        else:c['strict_pair_admitted_legs']+=1
                        reasons[key+'|pair_input'].update(why)
    result=dict(captured_at=at.isoformat(),window_end=end.isoformat(),games=games,new_engine_games=refreshed,
        engine=engine,cohorts={k:dict(v) for k,v in sorted(cohorts.items())},
        overlapping_reason_counts={k:dict(v) for k,v in sorted(reasons.items())},pair_search=dict(searches),
        counting_notes=['EV rows, candidate legs, and input/search refusal units are distinct denominators.',
            'Pair candidate legs cover only retained selected frames with a financial input bundle; other publications have no captured candidate census. This is not a complete candidate denominator.',
            'Numeric retained is not current; ordinary dashboard read is the currentness authority.',
            'Source offered denominator remains unknown; no 99% coverage conclusion.'],provider_requests=0)
    Path(destination).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('cohorts','overlapping_reason_counts')}))

if __name__=='__main__':run(sys.argv[1])
