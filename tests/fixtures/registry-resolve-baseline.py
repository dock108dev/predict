"""Independent pre-index lookup from HEAD 297bc9d93e3f9c33e2931c6355b1c520d9c8c0d1.

AST-equivalent to the frozen D04 resolver; retained as a portable test oracle.
"""
from app.normalization.names import name_key

def resolve(self, kind, name=None, *, league=None, venue=None, environment=None, native_id=None):
    if kind not in ('team', 'league'):
        raise ValueError('unsupported entity kind')
    native_id = None if native_id is None else str(native_id)
    provenance = ['name-key:v1']
    if kind == 'team' and league is not None:
        lr = self.resolve('league', league)
        if lr.status != 'resolved':
            return self.result('unknown', provenance=('unsupported-league-context',), name=name, native_id=native_id)
        league = lr.canonical_id
    named = set()
    if name is not None:
        for (k, lg, v, key), a in self.aliases.items():
            if k == kind and key == name_key(name) and (league is None or lg == league) and (v is None or v == venue):
                named.update(a['targets'])
                provenance.append(f"alias:{k}:{lg}:{v}:{a['text']}|{a['source']}")
    if kind == 'team' and league is None and (len(named) == 1):
        entity = self.entities[next(iter(named))]
        if name_key(name) not in (name_key(entity['name']), name_key(entity['id'])):
            return self.result('unknown', named, provenance + ['league-context-required-for-shorthand'], name, native_id)
    mapped = None
    if native_id is not None:
        if not venue or not environment or (kind == 'team' and league is None):
            return self.result('unknown', named, ('native-id-missing-scope',), name, native_id)
        m = self.native.get((kind, venue, environment, league if kind == 'team' else None, native_id))
        if m:
            mapped = m['target']
            provenance.append(f"native:{venue}:{environment}:{league}:{native_id}|{m['source']}")
        else:
            provenance.append('native-id-unmapped; name-only-resolution')
    if mapped is not None:
        if name is not None and mapped not in named:
            return self.result('conflicting', named | {mapped}, provenance + ['native-name-disagreement'], name, native_id)
        return self.result('resolved', [mapped], provenance, name, native_id)
    return self.result('resolved' if len(named) == 1 else 'ambiguous' if named else 'unknown', named, provenance + ([] if named else ['no-explicit-alias']), name, native_id)
