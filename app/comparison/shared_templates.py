"""Lossless successor storage for existing immutable calculation profiles.

Template references are storage indirection, never financial authority. Expansion
reproduces the exact legacy profile and its content identity. Legacy registries
retain their original limits/readers; current large registries use bounded bindings.
"""
from copy import deepcopy

from .current_dependencies import VERSION, KINDS, encoded, digest, public_tree, instant

VERSION_SHARED = 'comparison-current-dependencies-2'
TEMPLATE_VERSION = 'comparison-input-template-1'
BINDING_VERSION = 'comparison-input-binding-1'
REFERENCE = '$comparison_template'
# Template slots retain the old reusable-profile ceiling. Bindings follow the
# existing 16,000-quote * seven independent facet envelope. Bytes remain bounded.
MAX_TEMPLATES = 128
MAX_BINDINGS = 16000 * len(KINDS)
MAX_SHARED_BYTES = 24 * 1024 * 1024
MAX_BINDING_BYTES = 32768
REUSABLE = frozenset(('rule', 'engine_registry', 'grid', 'fill_inputs', 'fills',
    'source_evidence', 'normal_condition', 'scope', 'equality', 'payout_unknown',
    'below', 'equal', 'above', 'noncompleted'))


def shared(profiles):
    return isinstance(profiles, dict) and profiles.get('version') == VERSION_SHARED


def _expand(value, templates, kind, seen=()):
    if isinstance(value, dict):
        if REFERENCE in value:
            if set(value) != {REFERENCE}:
                raise ValueError('Exact template reference required')
            key=value[REFERENCE]
            if not isinstance(key,str) or key in seen or len(seen)>=24 or key not in templates:
                raise ValueError('Missing or cyclic comparison template')
            node=templates[key]
            if node['kind']!=kind:
                raise ValueError('Mismatched comparison template kind')
            return _expand(node['payload'],templates,kind,(*seen,key))
        return {k:_expand(v,templates,kind,seen) for k,v in value.items()}
    if isinstance(value,list):
        return [_expand(v,templates,kind,seen) for v in value]
    return value


def resolve(profiles, key):
    if not shared(profiles):return profiles[key]
    b=profiles['bindings'][key]
    return dict(version=VERSION,kind=b['kind'],
        payload=_expand(b['payload'],profiles['templates'],b['kind']),expires_at=b['expires_at'])


def keys(profiles):
    return profiles['bindings'].keys() if shared(profiles) else profiles.keys()


def validate(profiles):
    if set(profiles)!={'version','templates','bindings'}:
        raise ValueError('Exact shared comparison registry required')
    ts=profiles['templates'];bs=profiles['bindings']
    if not isinstance(ts,dict) or len(ts)>MAX_TEMPLATES or not isinstance(bs,dict) or len(bs)>MAX_BINDINGS:
        raise ValueError('Shared comparison template/binding capacity')
    if len(encoded(profiles))>MAX_SHARED_BYTES:
        raise ValueError('Shared comparison representation byte capacity')
    for key,node in ts.items():
        if not isinstance(node,dict) or set(node)!={'version','kind','payload'} or node['version']!=TEMPLATE_VERSION or node['kind'] not in KINDS:
            raise ValueError('Exact versioned comparison template required')
        if not isinstance(node['payload'],(dict,list)) or digest(node)!=key or len(encoded(node))>MAX_BINDING_BYTES:
            raise ValueError('Comparison template digest/byte mismatch')
        public_tree(node)
        _expand(node['payload'],ts,node['kind'],(key,))
    for key,b in bs.items():
        if not isinstance(b,dict) or set(b)!={'version','kind','payload','expires_at'} or b['version']!=BINDING_VERSION or b['kind'] not in KINDS:
            raise ValueError('Exact versioned comparison binding required')
        if not isinstance(b['payload'],dict) or len(encoded(b))>MAX_BINDING_BYTES:
            raise ValueError('Comparison binding byte capacity')
        public_tree(b['payload'])
        if b['expires_at'] is not None:instant(b['expires_at'])
        value=resolve(profiles,key)
        public_tree(value['payload'])
        if digest(value)!=key or len(encoded(value))>MAX_BINDING_BYTES:
            raise ValueError('Resolved comparison profile digest/byte mismatch')
    return profiles


class ProfilePool:
    """Per-admission builder with constant-time byte accounting and local refusal.

    Small historical registries keep their original representation. Promotion is
    lossless and only occurs when legacy capacity is reached, or explicitly asked.
    Immutable publication values never retain this mutable builder/cache.
    """
    def __init__(self, profiles=None, *, compact=False):
        from .current_dependencies import validate_profiles
        profiles={} if profiles is None else profiles
        validate_profiles(profiles)
        self.value=deepcopy(profiles)
        self.bytes=len(encoded(self.value));self.promoted=shared(self.value)
        if compact and not self.promoted:self.promote()

    def promote(self):
        old=self.value
        self.value=dict(version=VERSION_SHARED,templates={},bindings={})
        self.bytes=len(encoded(self.value));self.promoted=True
        for key,value in old.items():
            if not self.add(key,value):raise ValueError('Existing profile preservation capacity')

    def _intern(self, kind, value, field=None, additions=None):
        additions={} if additions is None else additions
        # Only declared structured slots are interned; no bare numeric merging.
        if isinstance(value,(dict,list)) and (field in REUSABLE or field=='root' and kind in ('buffer','probability')):
            node=dict(version=TEMPLATE_VERSION,kind=kind,payload=value)
            key=digest(node)
            if key in self.value['templates'] or key in additions:
                return {REFERENCE:key}
            if len(self.value['templates'])+len(additions)<MAX_TEMPLATES:
                additions[key]=node
                return {REFERENCE:key}
            # A full template table may fall back to a local binding. It does
            # not erase another healthy facet or remove a capacity bound.
        if isinstance(value,dict):
            return {k:self._intern(kind,v,k,additions) for k,v in value.items()}
        if isinstance(value,list):
            return [self._intern(kind,v,None,additions) for v in value]
        return value

    def add(self, key, value):
        from .current_dependencies import MAX_PROFILES, MAX_PROFILES_BYTES, validate_profiles
        if key in keys(self.value):return True
        # A producer profile is independently validated before any storage edit.
        validate_profiles({key:value})
        if not self.promoted:
            growth=len(encoded({key:value})) # conservative delimiters
            if len(self.value)<MAX_PROFILES and self.bytes+growth<=MAX_PROFILES_BYTES:
                self.value[key]=value;self.bytes+=growth;return True
            self.promote()
        additions={}
        payload=self._intern(value['kind'],value['payload'],'root',additions)
        b=dict(version=BINDING_VERSION,kind=value['kind'],payload=payload,expires_at=value['expires_at'])
        growth=len(encoded({key:b}))+len(encoded(additions))
        if len(self.value['bindings'])>=MAX_BINDINGS or self.bytes+growth>MAX_SHARED_BYTES:
            return False
        self.value['templates'].update(additions);self.value['bindings'][key]=b
        self.bytes+=growth
        return True

    def get(self,key,default=None):
        return resolve(self.value,key) if key in keys(self.value) else default

    def finish(self, reachable=None):
        if reachable is None:reachable=set(keys(self.value))
        if not self.promoted:return {k:v for k,v in self.value.items() if k in reachable}
        bs={k:v for k,v in self.value['bindings'].items() if k in reachable};seen=set()
        def visit(value):
            if isinstance(value,dict):
                if REFERENCE in value:
                    key=value[REFERENCE]
                    if key not in seen:
                        seen.add(key);visit(self.value['templates'][key]['payload'])
                else:
                    for v in value.values():visit(v)
            elif isinstance(value,list):
                for v in value:visit(v)
        for b in bs.values():visit(b['payload'])
        return dict(version=VERSION_SHARED,bindings=bs,templates={k:self.value['templates'][k] for k in sorted(seen)})


def subset(profiles, group):
    """A bounded group view for strict projection, without copying the slate."""
    from app.dashboard.current_contract import quotes_of
    wanted={key for o in group['outcomes'] for q in quotes_of(o)
        for key in q.get('comparison_input_refs',{}).get('refs',{}).values() if key is not None}
    if not shared(profiles):return {k:profiles[k] for k in wanted}
    bindings={k:profiles['bindings'][k] for k in wanted};templates={}
    def visit(value):
        if isinstance(value,dict):
            if REFERENCE in value:
                key=value[REFERENCE]
                if key not in templates:
                    templates[key]=profiles['templates'][key];visit(templates[key]['payload'])
            else:
                for v in value.values():visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    for b in bindings.values():visit(b['payload'])
    return dict(version=VERSION_SHARED,bindings=bindings,templates=templates)


class ProfileFactory:
    """Admission-local memo of exact policy/prior profiles, bounded to 128.

    Neither applicability nor original observations are inferred from a cache hit.
    The full kind/payload/expiration is the key; all other facets use the existing
    profile constructor. No cache survives publication or a provider/rule update.
    """
    def __init__(self):self.cache={};self.hits=0;self.misses=0

    def __call__(self, kind, payload, *, expires_at=None):
        from .current_dependencies import profile
        if kind not in ('buffer','probability'):
            return profile(kind,payload,expires_at=expires_at)
        fingerprint=encoded([kind,payload,expires_at])
        if fingerprint in self.cache:
            self.hits+=1;return self.cache[fingerprint]
        self.misses+=1;value=profile(kind,payload,expires_at=expires_at)
        if len(self.cache)<128:self.cache[fingerprint]=value
        return value
