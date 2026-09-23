"""Fail closed before native parsing; no inferred support for undocumented batches."""
import base64
import json


def violation(source, record, selection):
    kind=record.get('type')
    if kind not in ('prediction_command','prediction_frame','prediction_book','market_selected'):return None
    try:
        allowed=selection['subscription_ids'][source]
        mids=selection['markets'][source]
        if kind=='prediction_command':
            c=json.loads(record['body'])
            if source=='kalshi':
                if set(c)!= {'id','cmd','params'} or c['cmd']!='subscribe' or set(c['params'])!={'channels','market_tickers'} or c['params']['channels']!=['orderbook_delta']:return 'unsupported_subscription_command'
                ids=c['params']['market_tickers']
            else:
                if set(c)!={'subscribe'} or set(c['subscribe'])!={'requestId','subscriptionType','marketSlugs'} or c['subscribe']['subscriptionType']!='SUBSCRIPTION_TYPE_MARKET_DATA':return 'unsupported_subscription_command'
                ids=c['subscribe']['marketSlugs']
            if not isinstance(ids,list) or not ids or len(ids)>2 or len(set(ids))!=len(ids) or set(ids)!=set(allowed):return 'subscription_outside_frozen_selection'
        elif kind=='prediction_frame':
            c=json.loads(base64.b64decode(record['body_b64'],validate=True))
            # Native adapters support single objects only. Reject the whole batch before parsing.
            if not isinstance(c,dict):return 'unsupported_batch_or_envelope'
            if source=='kalshi':
                if c.get('type') in ('orderbook_snapshot','orderbook_delta'):
                    if not isinstance(c.get('msg'),dict):return 'unsupported_batch_or_envelope'
                    if c['msg'].get('market_ticker') not in allowed:return 'unsolicited_market'
                elif c.get('type')=='subscribed':
                    if set(c)-{'id','type','msg'} or set(c.get('msg',{}))-{'channel','sid'}:return 'unsupported_control_envelope'
                else:return 'unsupported_stream_envelope'
            else:
                if set(c)=={'heartbeat'} and isinstance(c['heartbeat'],dict):return None
                if set(c)-{'requestId','subscriptionType','marketData'} or not isinstance(c.get('marketData'),dict):return 'unsupported_batch_or_envelope'
                if c['marketData'].get('marketSlug') not in allowed:return 'unsolicited_market'
        else:
            ref=record['book' if kind=='prediction_book' else 'market']['raw']['ref']
            if ref['market_id'] not in mids or ref['event_id']!=selection[source]:return 'book_or_market_outside_frozen_selection'
    except (KeyError,ValueError,TypeError,AttributeError):return 'unverifiable_scope'
    return None
