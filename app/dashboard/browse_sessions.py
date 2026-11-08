"""Bounded browsing membership, revalidated against current price authority."""
from collections import OrderedDict
from threading import RLock
from time import monotonic
from uuid import uuid4
import json


class BrowseSessions:
    def __init__(self, *, clock=monotonic):
        self.sessions=OrderedDict();self.lock=RLock();self.clock=clock

    def page(self, groups, query, offset, limit):
        signature={k:v for k,v in query.items() if k not in ('offset','limit','expected_cursor','browse_id')}
        with self.lock:
            now=self.clock()
            for key in list(self.sessions):
                if now-self.sessions[key]['created']>900:self.sessions.pop(key)
            token=query.get('browse_id')
            if token:
                session=self.sessions.get(token)
                if not session or session['signature']!=signature:
                    return dict(state='page_changed',reason='Browsing snapshot expired or filters changed; refresh starts a new order.',rows=[])
                self.sessions.move_to_end(token)
            elif offset:
                return dict(state='page_changed',reason='Browsing snapshot missing; refresh starts a new order.',rows=[])
            else:
                order=[{k:g[k] for k in ('id','game_key','game_title','start_at')} for g in groups]
                size=len(json.dumps(order).encode())
                if size>8*1024*1024:raise ValueError('browse_membership_capacity')
                while self.sessions and (len(self.sessions)>=16 or sum(s['bytes'] for s in self.sessions.values())+size>8*1024*1024):
                    self.sessions.popitem(last=False)
                token=uuid4().hex
                session=dict(signature=signature,order=order,created=now,bytes=size)
                self.sessions[token]=session
            by_id={g['id']:g for g in groups}
            rows=[by_id.get(g['id'],dict(g,withdrawn=True,offers=[],reason='No longer in the current matching results. Refresh to update membership.'))
                  for g in session['order'][offset:offset+limit]]
            return dict(state='ready',rows=rows,total=len(session['order']),browse_id=token,
                browse_age_seconds=round(now-session['created'],3),
                browse_order='Membership and order retained; displayed evidence revalidated on every read.')
