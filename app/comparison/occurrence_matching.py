"""Bounded ordinary occurrence resolver. No price, payout or acquisition authority.

The registry retains source membership through schedule revisions. Metadata joins
are estimated, with exact originals beside the projected canonical identity.
Historical event keys and sealed direct-win proofs remain separate readers.
"""
from copy import deepcopy
from .event_links import digest, instant, reviewed_links

VERSION = 'predict-occurrence-match-1'
MAX_MEMBERS = 2048
UNKNOWN = (None, '', 'unknown', 'unverified')


def validate_match(value, source):
    from app.dashboard.current_contract import fields
    fields(value,{'version','occurrence_id','method','estimated','status','members','conflicts',
                  'candidate_members','original_event','original_market_identity','original_selection','revision'})
    if value['version']!=VERSION or value['revision']!=digest({k:v for k,v in value.items() if k!='revision'}):
        raise ValueError('Occurrence match revision conflict')
    if value['status'] not in ('matched','unresolved') or type(value['estimated']) is not bool:
        raise ValueError('Occurrence match status required')
    if not isinstance(value['members'],list) or not 1<=len(value['members'])<=MAX_MEMBERS:
        raise ValueError('Occurrence membership capacity')
    if not any((p['provider'],p['native_event_id'])==(source['provider'],source['native_event_id']) for p in value['members']):
        raise ValueError('Occurrence source membership conflict')
    if value['original_event']['id']!=source['native_event_id']:
        raise ValueError('Occurrence original source conflict')


class OccurrenceResolver:
    def __init__(self, *, links=None, overrides=None, aliases=None):
        self.links = reviewed_links() if links is None else links
        self.overrides = overrides
        self.aliases = aliases or {}
        self.members = {}

    def _participant(self, value, event, provider):
        if value in self.aliases:
            return self.aliases[value]
        from app.normalization.registry import Registry
        for name, cid in event['participants'].items():
            if cid == value:
                found = Registry.current().resolve('team', name, league=event['competition'], venue=provider)
                if found.status == 'resolved':
                    return found.canonical_id
        return value

    def _facts(self, record):
        e = record['event']; s = record['quote']['source']
        provider = s['provider']
        roles = {k: self._participant(e[k], e, provider) for k in ('home', 'away')}
        stated = e.get('source_participant_roles', {})
        conflict = any(self._participant(stated[k], e, provider) != roles[k]
                       for k in stated if k in roles)
        conflict |= bool(e.get('occurrence_conflict') or e.get('conflicting_duplicate'))
        shared = dict(e.get('shared_provider_ids', {}))
        raw = e.get('_native') or e.get('native_metadata') or {}
        if raw.get('sportradarGameId'):
            shared['sportradar'] = str(raw['sportradarGameId'])
        for fact in e.get('observed_identity_facts', []):
            # A bare vendor source_id does not name its identifier namespace.
            # Only typed provider attribution can promote it to a shared ID.
            if fact.get('source_provider') == 'sportradar' and fact.get('source_id'):
                old = shared.get('sportradar')
                if old and old != str(fact['source_id']):
                    conflict = True
                shared['sportradar'] = str(fact['source_id'])
        replacement = e.get('replacement_game_id') or raw.get('replacementGameId')
        if raw.get('rescheduledFromGameId') not in (None,0,'0'):
            replacement = replacement or str(raw['rescheduledFromGameId'])
        conflict |= len(set(roles.values())) != 2
        source_games = {str(fact['main_game_event_ticker']) for fact in e.get('observed_identity_facts', [])
            if provider == 'kalshi' and fact.get('main_game_event_ticker')}
        if provider == 'kalshi' and e.get('related_game_event_id'):
            source_games.add(str(e['related_game_event_id']))
        if len(source_games) > 1:
            conflict = True
        # Native spread/total series may use separate event IDs for the same
        # provider game. Only an explicit source link establishes that alias.
        source_game = next(iter(source_games)) if len(source_games) == 1 else s['native_event_id']
        return dict(key=(provider, s['native_event_id']), roles=roles,
                    source_game=source_game,
                    league=e['competition'], season=e.get('season'), stage=e.get('stage'),
                    game_number=e.get('game_number',raw.get('gameNumber')), shared=shared,
                    original_start=e.get('original_start') or raw.get('originalStartTime'),
                    start=e['scheduled_start'], replacement=replacement, conflict=conflict,
                    neutral=e.get('neutral_venue') is True,
                    version=s['binding_version'], evidence=record['quote']['provenance'].get('sha256'),
                    event=e)

    @staticmethod
    def _consistent(a, b):
        if a['league'] != b['league'] or set(a['roles'].values()) != set(b['roles'].values()):
            return False
        if a['roles'] != b['roles'] and not (a['neutral'] and b['neutral']):
            return False
        for field in ('season', 'stage', 'game_number', 'replacement'):
            if a[field] not in UNKNOWN and b[field] not in UNKNOWN and a[field] != b[field]:
                return False
        common = set(a['shared']) & set(b['shared'])
        return all(a['shared'][k] == b['shared'][k] for k in common)

    @classmethod
    def _metadata(cls, a, b):
        if not cls._consistent(a, b) or a['replacement'] or b['replacement']:
            return False
        # One explicit contextual witness is required. Missing source facts
        # remain unknown in that source's event and input adapters after a join.
        if any(a[k] in UNKNOWN and b[k] in UNKNOWN for k in ('season', 'stage')):
            return False
        if (a['game_number'] is None) != (b['game_number'] is None):
            return False
        if a['game_number'] != b['game_number']:
            return False
        starts = (a['original_start'] or a['start'], b['original_start'] or b['start'])
        return abs((instant(starts[0]) - instant(starts[1])).total_seconds()) <= 3600

    def resolve(self, records, *, clock):
        if len(records) > 16000:
            raise ValueError('Occurrence record capacity')
        at = instant(clock)
        facts = {}; conflicts = {}; source_local = set()
        for r in records:
            f = self._facts(r); k = f['key']
            admission = r.get('comparison_source_metadata', {}).get('comparison_admission', {})
            # A native price has a durable provider identity before its shared
            # comparison context is known. Retain it without promoting a typed
            # vendor ID or a remembered join into missing source context.
            if k[0] in ('kalshi', 'polymarket_us') and (
                    any(r['event'].get(field) in (None, '') for field in ('season', 'stage'))
                    or admission.get('reason') == 'comparison_context_missing'):
                source_local.add(k)
            if k in facts and digest({n:v for n,v in f.items() if n not in ('event', 'version', 'evidence')}) != digest({n:v for n,v in facts[k].items() if n not in ('event', 'version', 'evidence')}):
                conflicts[k] = ['contradictory_source_metadata']
            facts[k] = f
            if f['conflict']:
                conflicts[k] = ['source_role_or_identity_conflict']
        if len(facts) > MAX_MEMBERS:
            raise ValueError('Occurrence membership capacity')
        # Necessary-condition indexes only: the existing consistency/metadata
        # predicates still decide every candidate. Preserve original fact order
        # in audit output and retain peers sharing any (even conflicting) ID.
        order = {key: index for index, key in enumerate(facts)}
        shared_index, namespaces, role_groups = {}, {}, {}
        for key, fact in facts.items():
            role_groups.setdefault((fact['league'], frozenset(fact['roles'].values())), set()).add(key)
            for namespace, value in fact['shared'].items():
                shared_index.setdefault((namespace, value), set()).add(key)
                namespaces.setdefault(namespace, set()).add(key)
        assigned = {}; methods = {}; intervals = {}; edge_ids = {}
        source_groups={}
        for k,f in facts.items():
            source_groups.setdefault((k[0],f['source_game']),[]).append(k)
        # Shared provider identifiers outrank reviewed edges; disagreements fail.
        for k, f in sorted(facts.items()):
            if k in source_local:
                continue
            edge, reason = self.links.resolve(*k, f['league'], f['roles']['home'], f['roles']['away'], at)
            shared = sorted(f['shared'].items())
            if shared:
                assigned[k] = 'provider-game:' + digest([f['league'], shared])
                methods[k] = 'shared_provider_id'
            elif edge:
                assigned[k] = edge.occurrence_id
                methods[k] = 'reviewed_source_id'
            elif reason != 'provider_edge_review_required':
                conflicts.setdefault(k, []).append(reason)
            elif k in self.members and self._consistent(f, self.members[k]['facts']):
                assigned[k] = self.members[k]['occurrence_id']
                methods[k] = self.members[k]['method']
            elif k[0]=='the_odds_api':
                assigned[k]='provider-event:'+digest([f['league'],*k])
                methods[k]='shared_provider_event'
            if edge:
                # Use the reviewed occurrence as the durable shared-ID alias.
                if shared:
                    assigned[k] = edge.occurrence_id
                intervals[k] = dict(effective_from=edge.effective_from, effective_until=edge.effective_until)
                edge_ids[k] = [edge.id]
            elif shared and reason not in ('provider_edge_review_required','provider_edge_expired_or_not_effective'):
                conflicts.setdefault(k, []).append(reason)
        # Reconcile shared identifiers even if one member has a reviewed alias.
        for k, f in sorted(facts.items()):
            if k in source_local:
                continue
            peers = set().union(*(shared_index[(name, value)] for name, value in f['shared'].items()))
            peers = sorted(peers - {k} - source_local, key=order.get)
            if any(not self._consistent(f, facts[p]) for p in peers):
                for p in [k, *peers]:conflicts.setdefault(p, []).append('shared_id_metadata_conflict')
            ids = {assigned[p] for p in [k, *peers] if p in edge_ids}
            if len(ids) > 1:
                for p in [k, *peers]:conflicts.setdefault(p, []).append('reviewed_shared_id_conflict')
            elif ids:
                for p in [k, *peers]:assigned[p] = next(iter(ids))
            elif peers:
                previous={self.members[p]['occurrence_id'] for p in [k,*peers] if p in self.members
                          and self._consistent(facts[p],self.members[p]['facts'])}
                oid=min(previous) if previous else min(assigned[p] for p in [k,*peers] if p in assigned)
                for p in [k,*peers]:assigned[p]=oid
        # Mutual unique candidates only. This rejects repeated games and forks.
        candidates = {}
        for k, f in facts.items():
            if k in source_local:
                candidates[k] = []
                continue
            possible = set(role_groups[(f['league'], frozenset(f['roles'].values()))])
            possible.difference_update(source_local)
            for namespace, value in f['shared'].items():
                # A different value in any common namespace necessarily fails
                # _consistent. Missing namespaces remain candidates as before.
                possible.difference_update(namespaces[namespace] - shared_index[(namespace, value)])
            candidates[k] = [p for p in sorted(possible, key=order.get)
                if p[0] != k[0] and p not in conflicts and self._metadata(f, facts[p])]
        for k in sorted(facts):
            if k in source_local or k in conflicts or k in assigned and methods[k]!='shared_provider_event':continue
            peers = candidates[k]
            if peers and all(candidates[p].count(k) == 1 and
                             len({facts[x]['source_game'] for x in candidates[p] if x[0] == k[0]}) == 1 for p in peers):
                # All candidates must also agree with one another and not be
                # separate same-provider events or distinct strong identities.
                ids = {assigned[p] for p in peers if p in assigned and methods[p] != 'shared_provider_event'}
                source_members = {(p[0],facts[p]['source_game']) for p in peers}
                if (len(ids) <= 1 and len({p[0] for p in peers}) == len(source_members)
                        and all(p == q or self._metadata(facts[p],facts[q]) for p in peers for q in peers)):
                    oid = next(iter(ids)) if ids else 'metadata-game:' + digest(sorted([k,*peers]))
                    assigned[k] = oid; methods[k] = 'unique_metadata'
                    for p in peers:
                        if p not in assigned or methods[p] == 'shared_provider_event':assigned[p] = oid; methods[p] = 'unique_metadata'
                    continue
            if peers:conflicts[k] = ['ambiguous_metadata_candidates']
        # Source-local family aliases are a fallback after cross-source joins.
        # Giving them an independent strong ID earlier would create a second
        # identity competing with the same game's typed cross-provider witness.
        for (provider,game),members in source_groups.items():
            if provider!='kalshi' or len(members)<2 or any(k in source_local or k in conflicts for k in members):continue
            first=facts[members[0]]
            if not all(self._consistent(first,facts[k]) and instant(first['start'])==instant(facts[k]['start']) for k in members):continue
            ids={assigned[k] for k in members if k in assigned}
            if len(ids)>1:
                for k in members:conflicts.setdefault(k,[]).append('native_game_membership_conflict')
                continue
            oid=next(iter(ids)) if ids else 'native-game:'+digest([first['league'],provider,game])
            for k in members:
                if k not in assigned:assigned[k]=oid;methods[k]='shared_native_event'
        # Local reviewed overrides are explicit evidence, with the same expiry
        # and role checks. They cannot overrule a contradictory stronger identity.
        if self.overrides:
            for k,f in facts.items():
                if k in source_local or k in assigned or f['conflict']:continue
                edge, _ = self.overrides.resolve(*k,f['league'],f['roles']['home'],f['roles']['away'],at)
                if edge:
                    assigned[k] = edge.occurrence_id; methods[k] = 'local_reviewed_override'
                    conflicts.pop(k,None)
                    intervals[k] = dict(effective_from=edge.effective_from,effective_until=edge.effective_until)
                    edge_ids[k] = [edge.id]
        # An occurrence cannot contain two distinct IDs from one provider unless
        # explicit reviewed continuity associates both with that occurrence.
        by_occurrence = {}
        for key, oid in assigned.items():by_occurrence.setdefault(oid, []).append(key)
        for members in by_occurrence.values():
            for k in members:
                if any(not self._consistent(facts[k],facts[p]) for p in members):
                    conflicts.setdefault(k, []).append('occurrence_membership_conflict')
        output = []
        next_members = {}
        valid_members = {oid:sorted(key for key in members if key not in conflicts)
                         for oid,members in by_occurrence.items()}
        prior_occurrences = {}
        for prior in self.members.values():prior_occurrences.setdefault(prior['occurrence_id'], prior)
        for r in records:
            original = deepcopy(r); k = (r['quote']['source']['provider'],r['quote']['source']['native_event_id'])
            f = facts[k]; unresolved = k in conflicts or k not in assigned
            oid = None if unresolved else assigned[k]
            members = valid_members[oid] if oid else [k]
            audit = dict(version=VERSION, occurrence_id=oid, method='source_local' if unresolved else methods[k],
                         estimated=not unresolved and any(methods[p] == 'unique_metadata' for p in members),
                         status='unresolved' if unresolved else 'matched',
                         members=[dict(provider=p[0],native_event_id=p[1],provider_version=facts[p]['version'],
                                       evidence_sha256=facts[p]['evidence']) for p in members],
                         conflicts=sorted(set(conflicts.get(k, []))),
                         candidate_members=[list(p) for p in candidates[k]],
                         original_event=deepcopy(r['event']), original_market_identity=deepcopy(r['market_identity']),
                         original_selection=deepcopy(r['selection']))
            audit['revision'] = digest(audit)
            original['quote']['occurrence_match'] = audit
            if unresolved:
                from .event_links import provider_key
                original['market_identity']['event'] = provider_key(k[0],original['event'])
                aggregate = k[0] == 'the_odds_api'
                verified=aggregate or r['verified'] is True and k not in source_local and not f['conflict']
                original['event_scope'] = dict(policy='aggregate-provider-event-2' if aggregate else
                    'native-provider-event-1' if verified else 'native-event-unverified-2',
                    source=k[0] if aggregate else original['quote']['venue'],native_event_id=k[1])
                original['verified'] = verified
            if not unresolved:
                prior=prior_occurrences.get(oid)
                canonical_roles=prior['canonical_roles'] if prior else facts[members[0]]['roles']
                mapping = {r['event'][role]:f['roles'][role] for role in ('home','away')}
                e = original['event']
                e.update(game_id=oid,**canonical_roles)
                # Source spelling is preserved in original_event. NHL providers
                # use both hockey and ice_hockey for the same canonical sport.
                if e['competition']=='NHL' and e['sport'] in ('hockey','ice_hockey'):
                    e['sport']='hockey'
                    original['market_identity']['sport']='hockey'
                e['participants'] = {n:mapping.get(cid,cid) for n,cid in e['participants'].items()}
                from .event_links import ordinary_event_key
                original['market_identity']['event'] = ordinary_event_key(e)
                original.pop('event_scope',None)
                for value in [original['selection'],*original.get('outcome_selections',[])]:
                    value['participant'] = mapping.get(value['participant'],value['participant'])
                original['anchor_participant'] = mapping.get(original.get('anchor_participant'),original.get('anchor_participant'))
                original['verified'] = (original.get('comparison_source_metadata', {}).get('comparison_admission', {}).get('supported') is not False)
                # Matching provenance has its own dependency revision. Schedule
                # or peer membership changes do not reprice a native instrument.
                original['orientation_evidence'].append(VERSION+':'+digest([oid,k]))
                applicable=[intervals[p] for p in members if p in intervals]
                if applicable:
                    ends=[v['effective_until'] for v in applicable if v['effective_until'] is not None]
                    original['quote']['occurrence_link'] = dict(version=VERSION,
                        edges=sorted({edge for p in members for edge in edge_ids.get(p,[])}),
                        effective_from=max(v['effective_from'] for v in applicable),
                        effective_until=min(ends) if ends else None)
                next_members[k] = dict(occurrence_id=oid,method=methods[k],
                    facts=deepcopy({n:v for n,v in f.items() if n!='event'}),canonical_roles=canonical_roles)
            output.append(original)
        # Keep only the current admitted membership, under the existing latest
        # state bound; no learning from titles or historical quote archive.
        self.members = next_members
        return output
