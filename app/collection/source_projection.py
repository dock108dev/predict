"""Current aggregate presentation layered on the unchanged historical comparator."""
from decimal import Decimal
from app.reference.product import time
from app.dashboard.session_projection import stable


def current_aggregate(snapshot,settings,health,at,batches=()):
    current=snapshot['view_mode']=='current' and snapshot['state']=='current'
    state=health.get('state','pending')
    snapshot['source_session_version']=settings['version']
    snapshot['aggregate_health']=health
    snapshot['aggregate_batches']=list(batches)
    snapshot['cross_source_mapping']=dict(status='unavailable',reason='Explicit native contract/event crosswalk and compatible timing absent; provider-scoped comparisons only')
    for row in snapshot['aggregate_comparisons']:
        old=row['game_id']
        # A logical comparison survives polls, but its cutoff retains exact receipts.
        gid='aggregate-'+stable([row['identity'],row['outcome']])
        row.update(id=gid,game_id=gid,session=snapshot['session_id']+'~'+gid,historical=not current,mode=snapshot['data_mode'])
        for game in snapshot['games']:
            if game['id']==old:game['id']=gid
        snapshot['points'][gid]=snapshot['points'].pop(old)
        snapshot['rows_by_game'][gid]=snapshot['rows_by_game'].pop(old)
        receipt_ok=True
        for leg in row['legs']:
            context=next((b for b in batches if b['response_sha256']==leg['provenance']['response'] and b['received_at']==leg['received_at']),{})
            leg['processing_at']=context.get('processing_at');leg['admitted_at']=context.get('observed_at')
            age=Decimal(str((time(at)-time(leg['received_at'])).total_seconds()))
            try:source_age=None if not leg.get('source_at') else Decimal(str((time(at)-time(leg['source_at'])).total_seconds()))
            except (ValueError,TypeError,AttributeError):source_age=None
            recent=0<=age<=settings['stale_seconds'] and source_age is not None and 0<=source_age<=settings['stale_seconds']
            receipt_ok &= recent
            leg.update(age_seconds=str(age),source_age_seconds=None if source_age is None else str(source_age),
                       connection=state if current else 'saved',status='receipt recent; source delay unknown' if recent else 'stale or source time unknown')
            leg['warnings']+=['Provider delay and active/executable state unverified']
            if not recent:leg['warnings'].append('Aggregate receipt or provider timestamp stale or unknown')
            leg['transformation']=leg['transformation'].replace('Historical aggregated','Aggregated')
        row['timing']=dict(receipt_skew_seconds='0',receipt_limits_pass=bool(receipt_ok and current and state in ('connected','waiting')),
                           synchronized=False,reason='One response; independent book timestamps; provider delay and active state unverified')
        row['settlement']=row['settlement'].replace('Historical aggregated','Aggregated')
    for ref in snapshot['references']:
        if ref.get('provider_id')!='the_odds_api':continue
        ref['freshness']='unqualified source delay' if current else 'historical'
    for source in snapshot['sources']:
        if source['source_id'] in ('novig','prophetx'):
            source.update(state=state if current else 'saved',coverage=dict(state=state,reason=health.get('reason')),role='aggregate_comparison',
                          environment='simulated sequence' if snapshot['data_mode']=='synthetic' else 'aggregate observations',update_path='Shared Odds API session response')
    for book in ('pinnacle','draftkings','betmgm'):
        snapshot['sources'].append(dict(source_id=book,venue_id=book,provider_id='the_odds_api',origin_id=book,label=book,
            role='reference',state=state if current else 'saved',environment='reference input only',update_path='Shared Odds API session response'))
    if settings.get('correspondence_policy')=='source-correspondence-1':
        from app.reference.source_correspondence import augment
        augment(snapshot,settings,at)
