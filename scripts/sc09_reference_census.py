#!/usr/bin/env python3
"""Independent retained aggregate census; arithmetic is conditional, never net EV."""
import json,sys
from pathlib import Path
from collections import defaultdict,Counter
from fractions import Fraction as F
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,encoded


def census():
    counts=defaultdict(Counter);results=[]
    with connect() as db:
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            captured=db.execute('SELECT transaction_timestamp()::text at').fetchone()['at']
            with db.cursor(name='reference_census') as cursor:
                cursor.itersize=1
                cursor.execute("SELECT 'featured' kind,sport,received_at,payload->'events' events FROM current_acquisition_aggregate UNION ALL SELECT 'alternate',sport,received_at,jsonb_build_array(payload) FROM current_acquisition_alternate")
                for row in cursor:
                    for e in row['events']:
                        phase='pregame' if datetime.fromisoformat(e['commence_time'].replace('Z','+00:00'))>datetime.fromisoformat(captured) else 'started_or_past'
                        groups=defaultdict(list)
                        for book in e.get('bookmakers',[]):
                            for m in book.get('markets',[]):
                                family={'h2h':'moneyline','spreads':'spread','alternate_spreads':'spread','totals':'total','alternate_totals':'total'}.get(m['key'])
                                if not family:continue
                                for o in m.get('outcomes',[]):
                                    line=None if family=='moneyline' else str(F(str(o['point']))*(1 if family=='total' or o['name']==e['home_team'] else -1))
                                    groups[(book['key'],family,line)].append(dict(o,source_at=m.get('last_update') or book.get('last_update')))
                        for (venue,family,line),offered in groups.items():
                            c=counts['|'.join((row['kind'],venue,row['sport'],family))];c['received_outcomes']+=len(offered)
                            expected={'Over','Under'} if family=='total' else {e['home_team'],e['away_team']}
                            pair=groups.get(('pinnacle',family,line),[])
                            complete=len(pair)==2 and {o['name'] for o in pair}==expected and all(F(str(o['price']))>1 for o in pair)
                            for o in offered:
                                if F(str(o['price']))<=1:c['invalid_decimal_odds']+=1;continue
                                c['valid_decimal_odds']+=1
                                if venue=='pinnacle':c['reference_only']+=1;continue
                                if not complete:c['exact_reference_pair_absent_or_invalid']+=1;continue
                                selected=next((p for p in pair if p['name']==o['name']),None)
                                if selected is None:c['outcome_identity_absent']+=1;continue
                                if any(p['source_at'] is None for p in [o,*pair]):c['source_clock_unknown']+=1;continue
                                a=F(str(selected['price']));b=F(str(next(p for p in pair if p is not selected)['price']))
                                p=b/(a+b);edge=100*(p*F(str(o['price']))-1)
                                c['conditional_arithmetic_possible']+=1
                                c['conditional_arithmetic:'+phase]+=1
                                c['sign:'+('positive' if edge>0 else 'negative' if edge<0 else 'zero')]+=1
                                results.append(dict(kind=row['kind'],venue=venue,league=row['sport'],family=family,event=e['id'],title=e['away_team']+' vs '+e['home_team'],scheduled_start=e['commence_time'],event_phase=phase,line=line,outcome=o['name'],odds=o['price'],reference=[x['price'] for x in pair],return_percent=str(edge),source_at=o['source_at'],reference_clocks=[x['source_at'] for x in pair],received_at=row['received_at'].isoformat()))
    return dict(captured_at=captured,provider_requests=0,meaning='Conditional retained arithmetic only; no assertion of exceptional settlement equivalence, native mapping, net EV or execution.',cohorts={k:dict(v) for k,v in sorted(counts.items())},results=results)


if __name__=='__main__':
    report=census();Path(sys.argv[1]).write_bytes(encoded(report));print(json.dumps(dict(results=len(report['results']),cohorts=len(report['cohorts']))))
