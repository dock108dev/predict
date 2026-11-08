from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from app.collection.native_priority import select


def population():
    markets=[];events=[];metadata=[];now=datetime(2026,11,8,tzinfo=timezone.utc)
    for league in ('NFL','NBA','NCAAF','NCAAB','MLB','NHL'):
        for n in range(3):
            eid=f'{league}-{n}';events.append(dict(id=eid,competition=league,scheduled_start=(now+timedelta(hours=n)).isoformat()))
            for family in ('moneyline','spread','total'):
                for line in range(4):
                    mid=f'{eid}-{family}-{line}'
                    markets.append(SimpleNamespace(raw=SimpleNamespace(ref=SimpleNamespace(event_id=eid,market_id=mid))))
                    metadata.append(dict(id=mid,event_id=eid,market_type=family))
    return markets,dict(events=events,markets=metadata),now


def test_full_catalog_is_unchanged_and_every_deferred_market_receives_a_fair_slot():
    markets,catalog,now=population();original=list(markets);seen=set();fixed=None
    for offset in range(12):
        chosen,detail=select(markets,catalog,now,offset,limit=36)
        ids=[m.raw.ref.market_id for m in chosen]
        assert len(ids)==len(set(ids))==36
        if fixed is None:fixed=ids[:18]
        assert ids[:18]==fixed
        seen.update(ids)
        assert detail['eligible_markets']==216 and detail['deferred_markets']==180
        assert len(detail['cells'])==18
        assert all(c['active']>=1 for c in detail['cells'])
        assert sum(c['active']+c['deferred'] for c in detail['cells'])==216
    assert seen=={m.raw.ref.market_id for m in markets}
    assert markets==original and len(catalog['markets'])==216


def test_small_roster_needs_no_deferral_and_unknown_times_are_retained():
    markets,catalog,now=population();catalog['events'][0]['scheduled_start']=None
    chosen,detail=select(markets,catalog,now,0)
    assert {m.raw.ref.market_id for m in chosen}=={m.raw.ref.market_id for m in markets}
    assert detail['deferred_markets']==0
