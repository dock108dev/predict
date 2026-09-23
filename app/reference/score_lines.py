"""Explicit retained partition forecast. Never fits a distribution to a score/rating."""
import json
from app.reference.product import base,finish,time
from app.normalization.score_lines import VERSION,market_partitions,distribution,CONFIG


def score_distribution(r,binding,*,source_at=None,model_version=None):
    x=base(r,binding,source_at=source_at,model_version=model_version)
    i=x['market_identity'];native=json.loads(r['body'])
    from app.normalization.score_lines import partial as scope
    from app.normalization import score_periods,futures
    h1=scope(i) or futures.scope(i)
    if i['competition'] not in CONFIG or (i['family'] not in ('spread','total') and not h1) or (i['period']!='full_game' and not h1) or not isinstance(i['rules'],dict) or i['rules'].get('version')!=VERSION:raise ValueError('Reviewed pilot score-line identity required')
    if native.get('market_identity')!=i or native.get('participant')!=binding['participant'] or native.get('source_event_id')!=binding['source_event_id']:raise ValueError('Forecast exact market, partition or native outcome conflicts')
    if (futures if futures.scope(i) else CONFIG[i['competition']]).event_key(native.get('event',{}))!=i['event']:raise ValueError('Forecast event binding conflicts')
    if native.get('value_kind')!='score_partition_probability' or native.get('conditional_on')!=('explicit_championship_states' if futures.scope(i) else 'completed_'+i['period']+'_only' if score_periods.scope(i) else 'completed_first_half_only' if h1 else 'completed_full_game_exact_reviewed_nhl_settlement_score' if i['competition']=='NHL' else 'completed_full_game_including_extra_innings_action' if i['competition']=='MLB' else 'completed_full_game_including_overtime'):raise ValueError('Explicit completed-game score partition probabilities required; scores and ratings are unsupported')
    if i['competition']=='NHL' and native.get('settlement_score')!=i['rules'].get('settlement_score'):raise ValueError('NHL probability settlement-score convention missing or conflicting')
    parts=market_partitions(i)
    value=distribution(native.get('probabilities'),parts)
    x.update(parser='score_distribution',value_kind='partition_distribution',value=value,original_value=native['probabilities'],conversion_method='Explicit exact partition probabilities; no fitting',state='available',reason=None,partitions=parts)
    return finish(x)


def cutoff_reason(r):
    try:score_distribution(r['receipt'],r['binding'],source_at=r['source_at'],model_version=r['model_version'])
    except (ValueError,KeyError,TypeError):return 'Invalid exact score-partition probability binding'
    if r['source_at'] and time(r['source_at'])>time(r['received_at']):return 'Source publication time is later than receipt'
    if time(r['received_at'])>=time(r['market_identity']['scheduled_start']):return 'First received after scheduled start'
    return None
