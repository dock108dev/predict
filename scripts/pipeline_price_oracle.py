"""Independent exact arithmetic audit of retained normal-payout display prices."""
import json
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect
from app.dashboard.comparison_board import expand_price_fields,expand_odds

counts=Counter();fail=[];examples=[]
with connect() as db,db.transaction():
    db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    at=db.execute('select transaction_timestamp() at').fetchone()['at'].isoformat()
    with db.cursor(name='price_oracle') as cur:
        cur.itersize=1;cur.execute("select game_key,facts#>'{boards,odds}' b from latest_board")
        for row in cur:
            b=expand_odds(expand_price_fields(row['b']))
            for q in b['prices']:
                original=q['original'];shown=q.get('common_odds',{});units=original['units']
                if not shown.get('supported'):counts['unsupported_conversion']+=1;continue
                v=Fraction(original['value']);p=Fraction(original.get('payout','1'))
                if units=='decimal_odds':cost=1/v
                elif units=='american_odds':cost=100/(v+100) if v>0 else -v/(100-v)
                elif units=='usd_per_contract':cost=v/p
                else:counts['other_units']+=1;continue
                if not 0<cost<1:counts['boundary_prices']+=1;continue
                a=100*(1-cost)/cost if cost<=Fraction(1,2) else -100*cost/(1-cost)
                mag=abs(a);rounded=(2*mag.numerator+mag.denominator)//(2*mag.denominator)
                expected=('+' if a>0 else '-')+str(rounded)
                counts[q['venue']]+=1
                if expected!=shown['american']:fail.append(dict(quote_id=q['quote_id'],expected=expected,actual=shown['american']))
                if len(examples)<12:examples.append(dict(quote_id=q['quote_id'],source=q['venue'],original=original,exact_american=str(a),display=shown['american']))
result=dict(captured_at=at,method='Independent Fraction native cost/payout or odds; before costs; half-away rounding',checked=dict(counts),failures=fail,examples=examples,provider_requests=0)
Path(sys.argv[1]).write_text(json.dumps(result,indent=2)+'\n');print(dict(counts),len(fail),fail[:2])
if fail:raise SystemExit(1)
