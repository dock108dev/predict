"""One-time technical review materialization; not a general natural-language rule parser."""
from hashlib import sha256
from pathlib import Path
import json
root=Path(__file__).resolve().parents[2]
kalshi=json.loads((root/'evidence/phase-0/kalshi-nfl-markets.json').read_text())['markets']
pm=json.loads((root/'evidence/phase-0/pmus-nfl-events.json').read_text())['events']
ids={'74903','74902','74908','74901','74904'}
ks={'KXNFLGAME-26SEP13'+s for s in ('ATLPIT','BALIND','BUFHOU','CHICAR','CLEJAC')}
listings={}
for venue,rows in [('kalshi',[m for m in kalshi if m['event_ticker'] in ks]),('polymarket_us',[m for e in pm if str(e['id']) in ids for m in e['markets'] if m.get('marketType')=='moneyline'])]:
 for m in rows:
  text='\n\n'.join(m[k] for k in ('rules_primary','rules_secondary') if m.get(k)) if venue=='kalshi' else m['description']
  assert ('resolve to $0.50 for each team' if venue=='kalshi' else 'settle to $0.50') in text
  fields={'tie':{'value':'two-team-fraction-0.50','reason':'Explicit full-game listing tie clause.'},
          'listed_pitchers':{'value':'not-applicable-NFL','reason':'Confirmed NFL football event; this dimension concerns baseball pitcher conditions.'}}
  if venue=='kalshi':
   assert 'begins within 48 hours from its originally scheduled start time' in text
   fields['postponement']={'value':{'trigger':'begins_play','hours_from_original_start':48,'outside':'venue_fair_value'},'reason':'Listing explicitly measures commencement from original start instant.'}
  else:
   assert 'Overtime is included if played.' in text
   assert 'rescheduled to a date within two days of the originally scheduled date' in text
   fields['overtime']={'value':'included','reason':'Explicit listing statement.'}
   fields['postponement']={'value':None,'reason':'Listing requires rescheduling to a date within two days; timezone, date boundary and actual commencement requirement are not specified. Do not equate with Kalshi begins-play within 48 hours.'}
  fields['resumption']={'value':None,'reason':'Need reconciled suspension/resumption trigger, completion deadline and official-final exception for these listings; broad expiration guidance is insufficient.'}
  fields['settlement_sources']={'value':None,'reason':'Listing names governing body; fallback order and correction/review policy equivalence are unestablished.'}
  fields['deadlines']={'value':None,'reason':'Native expiration metadata retained; reconcile early expiration, result-review extensions and correction cutoff across exact listings.'}
  fields['fair_value']={'value':None,'reason':'No evidence binds independently determined venue fair values to equal or complementary payouts.'}
  fields['forfeit']={'value':None,'reason':'Kalshi pre-kickoff forfeit uses fair value; PMUS general forfeit-winner and pre-event-withdrawal clauses need precise applicability to a pre-kickoff NFL forfeit.'}
  fields['shortened_game']={'value':None,'reason':'Kalshi 55-minute/official-final clauses versus PMUS governing-body threshold; precise exceptional-case equivalence not established.'}
  fields['cancellation']={'value':None,'reason':'Cancellation versus postponement/resumption exception precedence and fair-value determination remain unaligned.'}
  fields['abandonment']={'value':None,'reason':'Need official-final, elapsed-play and restart-window branch equivalence.'}
  fields['venue_change']={'value':None,'reason':'Kalshi home/away reversal and scheduling-week exceptions versus general PMUS venue-change guidance need listing applicability review.'}
  fields['result_corrections']={'value':None,'reason':'First final result, corrections before expiration and discretionary review are not established equivalent.'}
  payouts={'tie':{'kind':'fraction','value':'0.50','reason':'Listing two-team tie settlement'},
           'postponed_outside_window':{'kind':'discretionary','reason':'Each listing uses its own window and venue fair value; scenario is outside that venue window.'}}
  listings[sha256(text.encode()).hexdigest()]={'dimensions':fields,'payouts':payouts}
record={'version':'listing-assessments-1','actor':'Codex (engineering technical assessment)',
        'reviewed_at':'2026-09-12','owner_acceptance':None,'pair_approvals':[],
        'scope':'Exact captured listing-text hashes only; source research in evidence/slice-8/research.',
        'general_sources':{m['file']:{'sha256':m['sha256'],
            'text_sha256':sha256((root/'evidence/slice-8/research'/('kalshi-nfl-rules.txt' if m['file']=='kalshi-nfl-rules.pdf' else m['file'])).read_bytes()).hexdigest()}
            for m in json.loads((root/'evidence/slice-8/research/sources.json').read_text())},
        'listings':listings}
(root/'app/fixtures/moneyline_rule_assessments.json').write_text(json.dumps(record,indent=2)+'\n')
print(len(listings),'reviewed listing texts')
