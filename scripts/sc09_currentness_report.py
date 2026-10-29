"""Summarize a complete ordinary captured slate, without acquiring or calculating."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.dashboard.comparison_board import expand_price_fields

cohorts=defaultdict(Counter);rows=[];capture=None;games=0
for path in sorted(Path(sys.argv[1]).glob('*.json')):
    page=json.loads(path.read_bytes())
    identity=[page['read_token'],page['read_revision'],page['read_at']]
    if capture is None:capture=identity
    assert identity==capture and page['provider_requests']==0 and not page['errors']
    for compact in page['boards']:
        board=expand_price_fields(compact);games+=1
        prices={p['quote_id']:p for p in board['prices']}
        for row in board['rows']:
            p=prices[row['price_ref']];event=next(g for g in page['games'] if g['game_key']==board['game_key'])
            selection=p['selection']
            family='total' if selection.get('predicate') in ('over','under') else 'spread' if selection.get('signed_line') is not None else 'moneyline'
            key='|'.join((p['venue'],event['league'],family));c=cohorts[key];c['result_rows']+=1
            for field in ('gross_decisive_benchmark','conditional_trade_benchmark'):
                metric=row.get(field) or {};name='gross' if field.startswith('gross') else 'conditional'
                state=metric.get('state','unavailable');c[name+':'+state]+=1
                if metric.get('available'):
                    reasons=metric.get('currentness_reasons',[])
                    assert state!='numeric_current' or not reasons
                    for reason in reasons:c[name+'_reason:'+reason]+=1
                    rows.append(dict(game=board['game_key'],quote=row['quote_id'],cohort=key,metric=name,
                        state=state,reasons=reasons,value=metric.get('return_percent'),original=p['original'],
                        source=p['source'],times=p['times'],reference=metric.get('reference_originals'),
                        calculated_at=board.get('calculated_at')))
                elif metric.get('reason'):c[name+'_refusal:'+metric['reason']]+=1
assert page['coverage']['complete'] and games==page['coverage']['total_games']
totals=Counter()
for c in cohorts.values():totals.update(c)
result=dict(capture=capture,games=games,provider_requests=0,totals=dict(totals),cohorts={k:dict(v) for k,v in sorted(cohorts.items())},rows=rows)
Path(sys.argv[2]).write_text(json.dumps(result,indent=2))
print(json.dumps(dict(games=games,totals=dict(totals))))
