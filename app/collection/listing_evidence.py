"""Offline native listing associations, separate from quote/settlement admission."""
from hashlib import sha256
from .coverage import decode_page

VERSION='native-listing-evidence-1'


def retained_us_futures(pages):
    """Bind complete retained event→market→side associations only.

    Descriptive listing text is a source claim, not reviewed settlement rules.
    Truncated responses never supply even prefix objects to this projection.
    """
    result=[]
    for page in pages:
        if (page.get('source')!='polymarket_us' or page.get('path')!='/v1/events'
                or page.get('status')!=200 or page.get('complete') is not True):continue
        _,body=decode_page(page)
        for event in body.get('events',[]):
            for market in event.get('markets',[]):
                if market.get('sportsMarketType')!='futures':continue
                sides=market.get('marketSides',[])
                reasons=[]
                if not event.get('id') or not market.get('id') or not market.get('slug'):
                    reasons.append('Missing native listing identity')
                if (len(sides)!=2 or {s.get('long') for s in sides}!={True,False}
                    or any(type(s.get('long')) is not bool or str(s.get('marketId'))!=str(market.get('id')) for s in sides)
                    or len({s.get('id') for s in sides})!=2):
                    reasons.append('Unresolved native side association')
                text=market.get('description')
                result.append(dict(version=VERSION,source='polymarket_us',response_sha256=page['body_sha256'],
                    received_at=page['received_at'],event_id=str(event.get('id')),event_title=event.get('title'),
                    market_id=str(market.get('id')),slug=market.get('slug'),title=market.get('question'),
                    listing_description=text,listing_description_sha256=sha256(text.encode()).hexdigest() if isinstance(text,str) else None,
                    sides=[dict(id=s.get('id'),market_id=s.get('marketId'),long=s.get('long'),label=s.get('description'),
                                team_id=s.get('teamId'),team_name=(s.get('team') or {}).get('name')) for s in sides],
                    association='unresolved' if reasons else 'observed_native_listing',reasons=reasons,
                    qualification='Source listing metadata only; no championship state table, complete field, settlement or execution qualification',
                    quotes_admitted=False,settlement_rules=None,fees=None,championship_identity=None))
    return result
