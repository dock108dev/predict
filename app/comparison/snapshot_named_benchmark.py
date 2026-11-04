"""Select captured named-book witnesses without substituting another source."""
from copy import deepcopy

from app.collection.current_benchmark import attach
from app.dashboard.current_contract import identity
from app.storage.store import hashed


def references(quotes, retained, settings):
    venue=settings['benchmark_venue']
    if venue=='pinnacle':return retained
    out=[]
    for row in quotes:
        record=row.get('original_record')
        if row.get('venue')!=venue or not record:continue
        q=record['quote']
        out.append(dict(id=hashed(q['source']),venue=venue,original_record=record,
            market=record['market_identity'],game_key=row['game_key'],
            original=q['original'],source=q['source'],times=q['times'],selection=record['selection']))
    return out


def bind(quotes, refs, settings):
    """Reuse the aggregate's exact semantic, receipt and signed-line pairing.

    Native prices need the separately supported snapshot identity path; no
    opaque provider ID, team label or missing scoring rule supplies that link.
    """
    venue=settings['benchmark_venue']
    if venue=='pinnacle':return quotes
    selected=[r['original_record'] for r in refs if r.get('original_record') and r['original_record'].get('verified') and r.get('source',{}).get('provider')=='the_odds_api']
    records=[deepcopy(r['original_record']) for r in quotes if r.get('original_record') and r['original_record'].get('verified') and r.get('source',{}).get('provider')=='the_odds_api']
    attach(records,selected,venue=venue)
    index={hashed(r['quote']['source']):r['quote'].get('sharp_reference') for r in records}
    out=[]
    for row in quotes:
        q=dict(row);out.append(q)
        q['reference']=None;q['benchmark_quote']=None
        if row.get('source',{}).get('provider')!='the_odds_api':continue
        ref=deepcopy(index.get(hashed(row['source'])))
        if not ref:continue
        ref['selection_digest']=identity('binding',row['binding']['selection'])
        q['reference']=ref
        q['benchmark_quote']=dict(id=row['quote_id'],revision=row.get('quote_revision',1),
            venue=row['venue'],source=row['source'],times=row['times'],original=row['original'],
            binding=row['binding'],display=row['common_odds'],state=row.get('source_state'),sharp_reference=ref)
    return out
