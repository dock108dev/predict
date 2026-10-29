"""Source-local display recovery; no matching or financial authority."""
from app.adapters.polymarket_us import full_game_family, side_ids
from app.collection.native_scope_bindings import series_binding


def display(source,metadata):
    if source=='kalshi':
        binding=series_binding(metadata.get('event_ticker','').split('-')[0])
        return dict(title=metadata.get('title'),period=binding['period'] if binding else 'unknown',
            sides=[dict(id=side,role=side.upper(),label=metadata.get(side+'_sub_title') or side.upper()) for side in ('yes','no')])
    if source=='polymarket_us':
        try:ids=side_ids(metadata)
        except ValueError:return {}
        sides=[]
        for s in metadata.get('marketSides',[]):
            team=s.get('team') or {};label=' · '.join(str(v) for v in (team.get('name'),s.get('description')) if v)
            item=dict(id=str(s['id']),role='Long' if s['long'] else 'Short',label=label or str(s['id']))
            if full_game_family(metadata.get('sportsMarketType'))=='spread':
                from decimal import Decimal,InvalidOperation
                try:
                    line=Decimal(str(s.get('description')))
                    if line.is_finite():item['line']=str(s['description'])
                except InvalidOperation:pass
            sides.append(item)
        return dict(title=metadata.get('question') or metadata.get('title'),
            period='full_game' if full_game_family(metadata.get('sportsMarketType')) else 'unknown',sides=sides)
    return {}
