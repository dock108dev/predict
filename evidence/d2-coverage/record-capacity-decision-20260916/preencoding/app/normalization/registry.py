"""Versioned local entity registry. Resolution never learns or writes mappings."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from types import MappingProxyType
from .names import name_key

DEFAULT_PATH = Path(__file__).with_name('registry-v1.json')


@dataclass(frozen=True)
class Resolution:
    status: str
    canonical_id: str | None
    canonical_name: str | None
    candidates: tuple[str, ...]
    provenance: tuple[str, ...]
    registry_version: str
    registry_sha256: str
    input_name: str | None = None
    native_id: str | None = None


class Registry:
    def __init__(self, data):
        self._data = json.loads(json.dumps(data))
        d = self._data
        if not isinstance(d, dict):
            raise ValueError('registry must be an object')
        for collection, required in {
            'entities': ('id', 'kind', 'name', 'source'),
            'aliases': ('kind', 'text', 'source'),
            'native_mappings': ('kind', 'venue', 'environment', 'native_id', 'target', 'source'),
        }.items():
            if not isinstance(d.get(collection), list):
                raise ValueError('registry collections must be arrays')
            for row in d[collection]:
                if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
                    raise ValueError('missing or invalid registry row fields')
                if collection == 'aliases' and (not isinstance(row.get('targets'), list) or any(not isinstance(t, str) for t in row['targets'])):
                    raise ValueError('alias targets must be an array of IDs')
                if row.get('league') is not None and not isinstance(row['league'], str):
                    raise ValueError('invalid league context')
                if row.get('venue') is not None and not isinstance(row['venue'], str):
                    raise ValueError('invalid venue context')
        if type(d.get('schema_version')) is not int or d.get('schema_version') != 1 or not isinstance(d.get('version'), str) or not d['version']:
            raise ValueError('unsupported registry version')
        self.version = d['version']
        self.entities = {}
        self.aliases = {}
        self.native = {}
        for e in d['entities']:
            if e['id'] in self.entities or e['kind'] not in ('league', 'team') or not name_key(e['name']) or not e['source']:
                raise ValueError('invalid or duplicate entity')
            self.entities[e['id']] = e.copy()
        for e in self.entities.values():
            if e['kind'] == 'team' and (e.get('league') not in self.entities or self.entities[e['league']]['kind'] != 'league'):
                raise ValueError('invalid team league')
        for a in d['aliases']:
            key = (a['kind'], a.get('league'), a.get('venue'), name_key(a['text']))
            targets = a['targets']
            if (a['kind'] == 'team' and a.get('league') is None) or (a['kind'] == 'league' and a.get('league') is not None):
                raise ValueError('alias league scope invalid')
            if not key[-1] or key in self.aliases or not targets or len(set(targets)) != len(targets) or not a['source']:
                raise ValueError('duplicate or invalid alias; use one explicit candidate set')
            for target in targets:
                e = self.entities.get(target)
                if not e or e['kind'] != a['kind'] or (a.get('league') and e.get('league') != a['league']):
                    raise ValueError('alias target kind/league mismatch')
            self.aliases[key] = a
        for e in self.entities.values():
            key = (e['kind'], e.get('league'), None, name_key(e['name']))
            if key not in self.aliases or self.aliases[key]['targets'] != [e['id']]:
                raise ValueError('canonical name must resolve uniquely')
        for m in d['native_mappings']:
            key = (m['kind'], m['venue'], m['environment'], m.get('league'), m['native_id'])
            e = self.entities.get(m['target'])
            if key in self.native or any(not isinstance(x, str) or not x for x in (m['venue'], m['environment'], m['native_id'], m['source'])):
                raise ValueError('duplicate or invalid native mapping')
            if not e or e['kind'] != m['kind'] or (m['kind'] == 'team' and e['league'] != m.get('league')):
                raise ValueError('native target kind/league mismatch')
            self.native[key] = m
        self.entities = MappingProxyType({k: MappingProxyType(v) for k, v in self.entities.items()})
        self.aliases = MappingProxyType({k: MappingProxyType({**v, 'targets': tuple(v['targets'])}) for k, v in self.aliases.items()})
        self.native = MappingProxyType({k: MappingProxyType(v.copy()) for k, v in self.native.items()})
        self.fingerprint = sha256(self.to_json().encode()).hexdigest()

    @classmethod
    def load(cls, path=DEFAULT_PATH):
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate JSON key')
                result[key] = value
            return result
        return cls(json.loads(Path(path).read_text(), object_pairs_hook=unique_pairs))

    def to_json(self):
        return json.dumps(self._data, indent=2, sort_keys=True) + '\n'

    def save(self, path):
        """Explicit validated snapshot save; atomic replacement on the same filesystem."""
        path = Path(path)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
            temporary = Path(f.name)
            try:
                f.write(self.to_json())
                f.flush()
                os.fsync(f.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def result(self, status, candidates=(), provenance=(), name=None, native_id=None):
        candidates = tuple(sorted(set(candidates)))
        identity = candidates[0] if status == 'resolved' and len(candidates) == 1 else None
        return Resolution(status, identity, self.entities[identity]['name'] if identity else None,
                          candidates, tuple(provenance), self.version, self.fingerprint, name, native_id)

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
        if kind == 'team' and league is None and len(named) == 1:
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
        return self.result('resolved' if len(named) == 1 else 'ambiguous' if named else 'unknown', named,
                           provenance + ([] if named else ['no-explicit-alias']), name, native_id)
