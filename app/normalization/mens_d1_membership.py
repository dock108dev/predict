"""Season-specific sponsorship evidence and reviewed exact identity aliases."""
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from app.normalization.college_registry import expanded
from app.normalization.names import name_key

_SEASON_START_MONTH = 8


@dataclass(frozen=True)
class MembershipSnapshot:
    season: str
    version: str
    members: dict
    aliases: dict

    def unresolved(self, reason='participant_membership_unverified'):
        return dict(division='unknown', season=self.season, membership_version=self.version,
                    canonical_id=None, reason=reason, sources=[])

    def lookup(self, source_team_id=None, name=None, *, canonical_id=None):
        # Sports Reference slug is retained with the source row. It has no
        # reviewed crosswalk unless a membership record explicitly supplies one.
        alias_target = self.aliases.get(name_key(name)) if name else None
        identity = canonical_id if canonical_id in self.members else None
        if identity and alias_target and identity != alias_target:
            return self.unresolved('participant_identity_disagreement')
        identity = identity or alias_target
        if not identity:
            return self.unresolved()
        return {**self.members[identity], 'canonical_id': identity if identity.startswith('NCAAB:') else None,
                'season': self.season, 'membership_version': self.version,
                'binding': 'canonical_registry_id' if canonical_id == identity else 'reviewed_exact_alias',
                'source_team_id': source_team_id, 'matched_label': name,
                'membership_record_id': identity}


def load_membership(day: date) -> MembershipSnapshot:
    start_year = day.year - (day.month < _SEASON_START_MONTH)
    return _membership(f'{start_year}-{start_year + 1}')


@lru_cache(maxsize=4)
def _membership(season: str) -> MembershipSnapshot:
    start_year, end_year = season.split('-')
    aliases_path = Path(__file__).with_name(f'mens-d1-aliases-{start_year}-{end_year[-2:]}.json')
    if not aliases_path.is_file():
        return MembershipSnapshot(season, f'{season}:unverified', {}, {})
    alias_blob = aliases_path.read_bytes()
    review = json.loads(alias_blob)
    if review['season'] != season:
        raise ValueError('mens_d1_alias_snapshot_season_mismatch')
    registry = expanded()
    members = {}
    candidates = {}

    def bind(label, identity):
        candidates.setdefault(name_key(label), set()).add(identity)

    for identity, entity in registry.entities.items():
        if entity.get('league') != 'NCAAB' or entity.get('gender') != 'men':
            continue
        evidence = entity.get('basketball_memberships', {}).get(season, {})
        if (evidence.get('competition_id') != 'NCAA:M:D1' or evidence.get('division') != 'I'
                or not evidence.get('source')):
            continue
        members[identity] = dict(division='d1', name=entity['name'], association='NCAA',
                                 classification='NCAA Division I', ncaa_org_id=entity.get('ncaa_org_id'),
                                 reclassifying=evidence.get('reclassifying'),
                                 sources=[evidence['source']], reason=None,
                                 membership_artifact='app/normalization/college-2026-27.json' if entity.get('ncaa_org_id')
                                 else 'app/normalization/registry-v1.json', alias_reviewed_on=review['reviewed_on'])
        bind(entity['name'], identity)
        for label in review['d1_aliases'].get(identity, ()):
            bind(label, identity)
    if not review['d1_aliases'].keys() <= members.keys():
        raise ValueError('mens_d1_alias_without_season_membership')
    for entity in review['non_d1']:
        identity = entity['id']
        members[identity] = dict(division='non_d1', name=entity['name'], classification=entity['classification'],
                                 sources=entity['sources'], reason='participant_not_ncaa_division_i',
                                 membership_artifact=f'app/normalization/{aliases_path.name}',
                                 alias_reviewed_on=review['reviewed_on'])
        for label in (*entity['aliases'], entity['name']):
            bind(label, identity)
    aliases = {key: targets.pop() for key, targets in candidates.items() if len(targets) == 1}
    version = f'{registry.version}:{sha256(alias_blob + registry.fingerprint.encode()).hexdigest()}'
    return MembershipSnapshot(season, version, members, aliases)


def membership_for_provider_team(canonical_id: str | None, *, day: date, label: str | None = None) -> dict:
    return load_membership(day).lookup(name=label, canonical_id=canonical_id)
