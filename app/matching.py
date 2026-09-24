"""Conservative event identity only. No market or execution semantics.

Single-writer local store; match complete batches, persist between collection runs.
"""
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from itertools import combinations
import json
import math
import os
from pathlib import Path
import tempfile

from app.normalization.observations import NormalizedEvent

VERSION = 'event-matcher-1'
SCHEMA = 1


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return sha256(packed(value).encode()).hexdigest()


def clone(value):
    return json.loads(packed(value))



def compact_raw(value):
    """Losslessly deduplicate repeated response bodies in exported JSON."""
    payloads = {}
    def visit(item):
        if isinstance(item, list):
            return [visit(x) for x in item]
        if not isinstance(item, dict):
            return item
        result = {k:visit(v) for k,v in item.items() if k != 'json_text'}
        if 'json_text' in item:
            body = item['json_text']
            h = sha256(body.encode()).hexdigest()
            payloads[h] = body
            result['json_text_sha256'] = h
        return result
    return visit(value), payloads


def expand_raw(value, payloads):
    for h,body in payloads.items():
        if sha256(body.encode()).hexdigest() != h:
            raise ValueError('raw payload hash mismatch')
    def visit(item):
        if isinstance(item,list): return [visit(x) for x in item]
        if not isinstance(item,dict): return item
        result = {k:visit(v) for k,v in item.items() if k != 'json_text_sha256'}
        if 'json_text_sha256' in item:
            result['json_text'] = payloads[item['json_text_sha256']]
        return result
    return visit(value)


def instant(value):
    dt = datetime.fromisoformat(value)
    if dt.utcoffset() is None:
        raise ValueError('schedule must be timezone-aware')
    return dt.astimezone(timezone.utc)


def observation(normalized: NormalizedEvent, *, artifact=None, schedule_status=None,
                game_number=None, evidence_source=None):
    """Consume normalized participant and league records. Optional schedule/game labels need explicit provenance.

    Start always comes from Event.scheduled_start, never an unrelated timestamp.
    Unknown native lifecycle/game-number formats must be translated by a caller
    with a cited field, not guessed from a title by this matcher.
    """
    e = normalized.observation
    if not normalized.environment or not e.raw.ref.event_id:
        raise ValueError('environment and native event reference required')
    if game_number is not None and (type(game_number) is not int or game_number < 1):
        raise ValueError('game_number must be a positive integer')
    status = schedule_status or ('known' if e.scheduled_start else 'missing')
    if status not in {'known', 'missing', 'uncertain', 'postponed', 'canceled'}:
        raise ValueError('unsupported schedule status')
    if status == 'known' and e.scheduled_start is None:
        raise ValueError('known schedule requires a start')
    if (schedule_status is not None or game_number is not None) and not evidence_source:
        raise ValueError('explicit schedule metadata requires evidence_source')
    raw = json.loads(json.dumps(asdict(normalized), default=lambda x: x.isoformat()))
    scope = [e.raw.kind.value, normalized.environment]
    key = packed([*scope, e.raw.ref.venue.value, e.raw.ref.event_id])
    ids = sorted(p.resolution.canonical_id for p in normalized.participants
                 if p.resolution.status == 'resolved' and p.resolution.canonical_id)
    # Generic enrichment has no reviewed college gender/division/game fields.
    # NCAAB equivalence is established only by the ordinary bounded review path.
    valid = (normalized.league.canonical_id != 'NCAAB'
             and normalized.league.status == 'resolved' and len(ids) == 2
             and len(normalized.participants) == 2 and len(set(ids)) == 2
             and all(i.startswith(normalized.league.canonical_id + ':') for i in ids))
    roles = {p.resolution.canonical_id: p.role for p in normalized.participants
             if p.role in ('home', 'away') and p.resolution.status == 'resolved'}
    role_conflict = len(roles) == 2 and len(set(roles.values())) != 2
    versions = sorted({(r.registry_version, r.registry_sha256) for r in
                       [normalized.league, *(p.resolution for p in normalized.participants)]})
    result = {'key':key, 'scope':scope, 'venue':e.raw.ref.venue.value,
              'native_event_id':e.raw.ref.event_id, 'environment':normalized.environment,
              'league':normalized.league.canonical_id, 'participants':ids,
              'valid_identity':valid and len(versions) == 1, 'roles':roles,
              'role_conflict':role_conflict,
              'uninterpreted_roles':[p.role for p in normalized.participants if p.role is not None and p.role not in ('home','away')], 'start':e.scheduled_start.isoformat() if e.scheduled_start else None,
              'schedule_status':status, 'game_number':game_number,
              'schedule_source':evidence_source or 'Event.scheduled_start (adapter event start only)',
              'registry':versions, 'raw_sha256':sha256(e.raw.json_text.encode()).hexdigest(),
              'artifact':artifact, 'normalized_observation':raw}
    result['hash'] = digest(result)
    return clone(result)


def facts(o):
    result = {k:o[k] for k in ('scope','league','participants','valid_identity','roles',
                            'role_conflict','uninterpreted_roles','start','schedule_status','game_number','registry')}
    result['start'] = instant(o['start']).isoformat() if o['start'] else None
    return result


def compare(a, b, tolerance):
    reasons = []
    if a['scope'] != b['scope']:
        return 'unmatched', ['environment-or-evidence-kind-isolated']
    if not a['valid_identity'] or not b['valid_identity']:
        return 'unmatched', ['unresolved-or-inconsistent-identities']
    if (a['league'], a['participants']) != (b['league'], b['participants']):
        return 'unmatched', ['different-league-or-participants']
    if a['registry'] != b['registry']:
        return 'conflicting', ['normalization-registry-disagreement']
    if a['role_conflict'] or b['role_conflict'] or any(
        a['roles'][p] != b['roles'][p] for p in a['roles'].keys() & b['roles'].keys()):
        return 'conflicting', ['explicit-role-conflict']
    combined_roles = {**a['roles'], **b['roles']}
    if len(combined_roles) == 2 and len(set(combined_roles.values())) != 2:
        return 'conflicting', ['explicit-role-conflict']
    if a['uninterpreted_roles'] or b['uninterpreted_roles']:
        return 'candidate', ['uninterpreted-explicit-role-label']
    if a['game_number'] and b['game_number'] and a['game_number'] != b['game_number']:
        return 'conflicting', ['different-game-numbers']
    if a['schedule_status'] != 'known' or b['schedule_status'] != 'known':
        return 'candidate', ['missing-uncertain-or-inactive-schedule']
    delta = abs((instant(a['start']) - instant(b['start'])).total_seconds())
    if delta > tolerance:
        return 'conflicting', ['start-times-outside-tolerance; repeat-game-or-reschedule-unresolved']
    reasons += ['resolved-same-league-and-unordered-participants',
                'explicit-roles-compatible; missing-roles-not-inferred',
                f'aware-start-difference={delta:g}s<=tolerance={tolerance:g}s',
                'game-numbers-compatible-or-unsupplied']
    return 'matched', reasons


class Matcher:
    def __init__(self, *, tolerance_seconds=900):
        if (isinstance(tolerance_seconds, bool) or not isinstance(tolerance_seconds, (int,float))
                or not math.isfinite(tolerance_seconds) or tolerance_seconds < 0):
            raise ValueError('tolerance must be finite and nonnegative')
        self._data = {'schema_version':SCHEMA, 'matcher_version':VERSION,
                      'tolerance_seconds':tolerance_seconds, 'observations':{},
                      'current':{}, 'pending':{}, 'canonicals':{}, 'mappings':{}, 'revisions':[], 'reviews':[]}

    @property
    def snapshot(self):
        return clone(self._data)

    def _decision(self, key, status, canonical, reasons, hashes, candidates=()):
        row = {'key':key,'status':status,'canonical_id':canonical, 'reasons':sorted(set(reasons)),
               'observation_hashes':sorted(set(hashes)), 'candidates':sorted(set(candidates)),
               'matcher_version':VERSION}
        previous = self._data['mappings'].get(key)
        if previous and {k:v for k,v in previous.items() if k != 'revision'} == row:
            return
        row['revision'] = (previous['revision'] if previous else 0) + 1
        self._data['revisions'].append({'key':key,'before':clone(previous),'after':clone(row)})
        self._data['mappings'][key] = row

    def ingest(self, observations):
        # Store byte-equivalent semantic envelopes once; never mutate history.
        prior = clone(self._data['mappings'])
        revision_count = len(self._data['revisions'])
        incoming = {}
        for original in observations:
            o = clone(original)
            h = o.pop('hash')
            if digest(o) != h:
                raise ValueError('observation hash mismatch')
            o['hash'] = h
            incoming[h] = o
        pending = {}
        for h, o in sorted(incoming.items()):
            if h not in self._data['observations']:
                self._data['observations'][h] = o
                pending.setdefault(o['key'], []).append(h)
        for key, hashes in sorted(pending.items()):
            old = self._data['current'].get(key)
            all_hashes = sorted(set(hashes + ([old] if old else [])))
            variants = {packed(facts(self._data['observations'][h])) for h in all_hashes}
            if len(variants) > 1:
                self._data['pending'][key] = sorted(set(self._data['pending'].get(key, []) + hashes))
                prev = self._data['mappings'].get(key, {})
                self._decision(key, 'conflicting', prev.get('canonical_id'),
                               ['conflicting-native-update; retained-prior-identity; explicit-review-required'],
                               [h for h,o in self._data['observations'].items() if o['key']==key])
            else:
                self._data['current'][key] = old or all_hashes[0]
        self._reconcile()
        self._collapse_revisions(prior, revision_count)
        return self.snapshot

    def _collapse_revisions(self, prior, count):
        final = clone(self._data['mappings'])
        self._data['mappings'] = prior
        del self._data['revisions'][count:]
        for key,m in sorted(final.items()):
            self._decision(key,m['status'],m['canonical_id'],m['reasons'],
                           m['observation_hashes'],m['candidates'])

    def _reconcile(self):
        # Compute final decisions before recording revisions: temporary component
        # decisions must not cause audit churn when a retained group fails a gate.
        prior = clone(self._data['mappings'])
        count = len(self._data['revisions'])
        self._calculate()
        self._collapse_revisions(prior, count)

    def _calculate(self):
        d = self._data
        rows = {k:d['observations'][h] for k,h in d['current'].items()
                if k not in d['pending']}
        pairs = {}
        neighbors = {k:set() for k in rows}
        for a,b in combinations(sorted(rows),2):
            x,y = rows[a],rows[b]
            status,reasons = compare(x,y,d['tolerance_seconds'])
            pairs[a,b] = (status,reasons)
            same = (x['scope'],x['league'],x['participants']) == (y['scope'],y['league'],y['participants'])
            # Disjoint known game numbers and distant known starts are separate
            # candidates. Missing evidence can connect multiple games -> ambiguity.
            number_split = x['game_number'] and y['game_number'] and x['game_number'] != y['game_number']
            distant = (x['start'] and y['start'] and x['schedule_status']=='known' and y['schedule_status']=='known'
                       and abs((instant(x['start'])-instant(y['start'])).total_seconds()) > d['tolerance_seconds'])
            if same and x['valid_identity'] and y['valid_identity'] and not number_split and not distant:
                neighbors[a].add(b); neighbors[b].add(a)
        unseen = set(rows)
        while unseen:
            seed = min(unseen); component = {seed}; todo = [seed]
            while todo:
                for nxt in neighbors[todo.pop()] - component:
                    component.add(nxt); todo.append(nxt)
            unseen -= component
            keys = sorted(component)
            checks = [pairs[a,b] for a,b in combinations(keys,2)]
            old_ids = {d['mappings'][k]['canonical_id'] for k in keys
                       if d['mappings'].get(k,{}).get('canonical_id')}
            hashes = [rows[k]['hash'] for k in keys]
            reasons = [r for _,rs in checks for r in rs]
            valid = all(rows[k]['valid_identity'] and not rows[k]['role_conflict'] for k in keys)
            known = all(rows[k]['schedule_status']=='known' and not rows[k]['uninterpreted_roles'] for k in keys)
            if any(rows[k]['uninterpreted_roles'] for k in keys):
                reasons += ['uninterpreted-explicit-role-label']
            duplicate_venue = len({rows[k]['venue'] for k in keys}) != len(keys)
            if not valid:
                status = 'conflicting' if any(rows[k]['role_conflict'] for k in keys) else 'unmatched'
                reasons += ['unresolved-identities-or-internal-role-conflict']
            elif len(old_ids) > 1:
                status = 'ambiguous'; reasons += ['multiple-persisted-canonicals; no-automatic-merge']
            elif duplicate_venue:
                status = 'ambiguous'; reasons += ['distinct-native-events-at-same-venue; possible-repeat-or-recreated-listing']
            elif any(s == 'conflicting' for s,_ in checks):
                status = 'ambiguous' if len(keys)>2 else 'conflicting'
                reasons += ['all-pairs-constraint-failed; no-transitive-merge']
            elif not known:
                status = 'ambiguous' if len(keys)>2 else ('candidate' if len(keys)>1 else 'unmatched')
                reasons += ['missing-uncertain-or-inactive-schedule']
            else:
                status = 'matched' if len(keys)>1 else 'unmatched'
                if len(keys)==1: reasons += ['no-confirmed-peer; singleton-event']
            canonical = None
            if valid and known and status in ('matched','unmatched'):
                canonical = next(iter(old_ids)) if old_ids else 'event-' + digest(keys)[:24]
                if canonical not in d['canonicals']:
                    first = rows[keys[0]]
                    d['canonicals'][canonical] = {'id':canonical,'scope':first['scope'],
                        'league':first['league'],'participants':first['participants'],
                        'initial_observation_hashes':sorted(hashes),'creation_keys':keys,
                        'matcher_version':VERSION}
            for key in keys:
                prior_id = d['mappings'].get(key,{}).get('canonical_id')
                if prior_id and canonical is None:
                    reasons_for_key = reasons + ['prior-canonical-retained; current-decision-not-confirmed']
                else:
                    reasons_for_key = reasons
                own_hashes = [h for h,o in d['observations'].items() if o['key']==key]
                self._decision(key,status,canonical or prior_id,reasons_for_key,own_hashes,
                               [k for k in keys if k != key])

        # A retained ID may span disconnected components after a schedule update.
        # Validate the whole persisted group, not just the new candidate component.
        for cid in sorted(d['canonicals']):
            members = sorted(k for k,m in d['mappings'].items() if m['canonical_id']==cid)
            bad = any(k in d['pending'] for k in members)
            evidence = [d['observations'][d['current'][k]] for k in members if k in d['current']]
            bad = bad or any(compare(a,b,d['tolerance_seconds'])[0] != 'matched'
                             for a,b in combinations(evidence,2))
            if bad:
                for k in members:
                    m = d['mappings'][k]
                    self._decision(k,'conflicting',cid,
                        m['reasons'] + ['persisted-group-has-conflicting-or-pending-evidence'],
                        m['observation_hashes'],m['candidates'])

    def review_schedule(self, key, observation_hash, *, reason, actor, source):
        """Accept only schedule/lifecycle corrections on an existing native identity.

        Other listing evidence is re-evaluated; disagreement blocks confirmation.
        """
        if not all(isinstance(v,str) and v.strip() for v in (reason,actor,source)):
            raise ValueError('review requires reason, actor and source')
        d = self._data
        new = d['observations'][observation_hash]
        old = d['observations'][d['current'][key]]
        if new['key'] != key or any(new[f] != old[f] for f in
                ('scope','league','participants','valid_identity','roles','role_conflict','uninterpreted_roles','game_number','registry')):
            raise ValueError('review supports schedule corrections only, same resolved native identity')
        if not new['valid_identity']:
            raise ValueError('unresolved identity cannot be reviewed as confirmed')
        d['reviews'].append({'action':'accept-schedule-correction','key':key,
            'before':old['hash'],'after':observation_hash,'reason':reason,'actor':actor,'source':source})
        d['current'][key] = observation_hash
        d['pending'].pop(key,None)
        prev = d['mappings'][key]
        self._decision(key,'candidate',prev['canonical_id'],['explicit-schedule-review; re-evaluation-required'],
                       prev['observation_hashes'])
        self._reconcile()
        return self.snapshot

    def report(self):
        d = self.snapshot
        d['events'] = []
        for cid,event in sorted(d['canonicals'].items()):
            listings = []
            for key,m in sorted(d['mappings'].items()):
                if m['canonical_id'] != cid:
                    continue
                o = d['observations'][d['current'][key]]
                listings.append({'key':key,'venue':o['venue'],'native_event_id':o['native_event_id'],
                    'environment':o['environment'],'start':o['start'],'schedule_status':o['schedule_status'],
                    'roles':o['roles'],'game_number':o['game_number'],'mapping_status':m['status'],
                    'current_observation_hash':o['hash'],'all_observation_hashes':m['observation_hashes']})
            d['events'].append({**event,'listings':listings,
                'decision_statuses':sorted({x['mapping_status'] for x in listings})})
        d['comparisons'] = []
        for a,b in combinations(sorted(d['current']),2):
            x,y = (d['observations'][d['current'][k]] for k in (a,b))
            if (x['league'],x['participants']) != (y['league'],y['participants']):
                continue
            status,reasons = compare(x,y,d['tolerance_seconds'])
            d['comparisons'].append({'left':a,'right':b,'status':status,'reasons':reasons,
                                     'comparison_only':True,
                                     'automatic_match':(d['mappings'][a]['status']=='matched'
                                         and d['mappings'][b]['status']=='matched'
                                         and d['mappings'][a]['canonical_id']==d['mappings'][b]['canonical_id']),
                                     'evidence':[x['hash'],y['hash']]})
        return d

    def envelope(self):
        data,raw_payloads=compact_raw(self._data)
        return dict(data=data,raw_payloads=raw_payloads,sha256=digest(data))

    def save(self, path):
        path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
        data, raw_payloads = compact_raw(self._data)
        payload = {'data':data,'raw_payloads':raw_payloads,'sha256':digest(data)}
        fd, name = tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
        try:
            with os.fdopen(fd,'w') as stream:
                stream.write(packed(payload)+'\n'); stream.flush(); os.fsync(stream.fileno())
            os.replace(name,path)
            directory = os.open(path.parent,os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if os.path.exists(name): os.unlink(name)

    @classmethod
    def load(cls,path):
        def unique(pairs):
            result = {}
            for k,v in pairs:
                if k in result: raise ValueError('duplicate store key')
                result[k] = v
            return result
        envelope = json.loads(Path(path).read_text(),object_pairs_hook=unique)
        return cls.from_envelope(envelope)

    @classmethod
    def from_envelope(cls,envelope):
        d = envelope['data']
        if envelope['sha256'] != digest(d): raise ValueError('store checksum mismatch')
        d = expand_raw(d,envelope.get('raw_payloads',{}))
        if d['schema_version'] != SCHEMA or d['matcher_version'] != VERSION:
            raise ValueError('unsupported store/matcher version; explicit migration required')
        result = cls(tolerance_seconds=d['tolerance_seconds'])
        for h,o in d['observations'].items():
            if h != o['hash'] or digest({k:v for k,v in o.items() if k!='hash'}) != h:
                raise ValueError('invalid stored observation')
        for key,h in d['current'].items():
            if d['observations'][h]['key'] != key: raise ValueError('invalid current reference')
        for key,m in d['mappings'].items():
            if m['key'] != key or (m['canonical_id'] and m['canonical_id'] not in d['canonicals']):
                raise ValueError('invalid mapping reference')
            for h in m['observation_hashes']:
                if d['observations'][h]['key'] != key: raise ValueError('invalid mapping evidence')
        for key,hashes in d['pending'].items():
            if not hashes or any(d['observations'][h]['key'] != key for h in hashes):
                raise ValueError('invalid pending evidence')
        for cid,c in d['canonicals'].items():
            if cid != c['id'] or cid != 'event-' + digest(c['creation_keys'])[:24]:
                raise ValueError('invalid canonical identity')
            if any(h not in d['observations'] for h in c['initial_observation_hashes']):
                raise ValueError('invalid canonical evidence')
        audit = {}
        for r in d['revisions']:
            key = r['key']
            if r['before'] != audit.get(key):
                raise ValueError('broken revision chain')
            m = r['after']
            if (m['key'] != key or m['revision'] != (audit[key]['revision']+1 if key in audit else 1)
                    or m['status'] not in {'matched','candidate','ambiguous','conflicting','unmatched'}):
                raise ValueError('invalid decision revision')
            audit[key] = m
        if audit != d['mappings']:
            raise ValueError('current mappings disagree with revision history')
        for review in d['reviews']:
            if not all(review[k] for k in ('reason','actor','source')) or any(
                    d['observations'][review[k]]['key'] != review['key'] for k in ('before','after')):
                raise ValueError('invalid review provenance')
        result._data = d
        return result
