"""Bounded browsing membership, revalidated against current price authority."""
from collections import OrderedDict
from threading import RLock
from time import monotonic
from uuid import uuid4
import json


def locate_page(groups, query, offset, limit, *, order=None):
    """Find a return anchor in the eligible groups, preserving the session order."""
    anchor = query.get('locate')
    if not anchor:
        return offset, None
    game_key = query.get('locate_game')
    members = {group['id']: group for group in groups}
    order = groups if order is None else order
    fallback = None
    nearest = None
    for index, entry in enumerate(order):
        group = members.get(entry['id'])
        if not group:
            continue
        page = index // limit * limit
        if group['id'] == anchor or any(outcome['id'] == anchor for outcome in group.get('outcomes', ())):
            return page, 'exact'
        if game_key and fallback is None and group['game_key'] == game_key:
            fallback = page
        if nearest is None or abs(page - offset) < abs(nearest - offset):
            nearest = page
    if fallback is not None:
        return fallback, 'game'
    return nearest or 0, 'removed'


class BrowseSessions:
    def __init__(self, *, clock=monotonic):
        self.sessions=OrderedDict();self.lock=RLock();self.clock=clock

    def page(self, groups, query, offset, limit):
        signature={k:v for k,v in query.items()
                   if k not in ('offset','limit','expected_cursor','browse_id','locate','locate_game')}
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
                token = next((key for key in reversed(self.sessions)
                              if self.sessions[key]['signature'] == signature
                              and self.sessions[key]['order'] == order), None)
                if token:
                    session = self.sessions[token]
                    self.sessions.move_to_end(token)
                else:
                    size=len(json.dumps(order).encode())
                    if size>8*1024*1024:raise ValueError('browse_membership_capacity')
                    while self.sessions and (len(self.sessions)>=16 or sum(s['bytes'] for s in self.sessions.values())+size>8*1024*1024):
                        self.sessions.popitem(last=False)
                    token=uuid4().hex
                    session=dict(signature=signature,order=order,created=now,bytes=size)
                    self.sessions[token]=session
            by_id={g['id']:g for g in groups}
            offset, anchor_state = locate_page(groups, query, offset, limit, order=session['order'])
            rows=[by_id.get(g['id'],dict(g,withdrawn=True,offers=[],reason='No longer in the current matching results. Refresh to update membership.'))
                  for g in session['order'][offset:offset+limit]]
            return dict(state='ready',rows=rows,total=len(session['order']),browse_id=token,
                offset=offset, anchor_state=anchor_state,
                browse_age_seconds=round(now-session['created'],3),
                browse_order='Membership and order retained; displayed evidence revalidated on every read.')
