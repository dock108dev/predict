"""Dated retained candidate diagnostics; never supplies calculation authority."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from .event_links import digest
from .source_inputs import observation

PATH = Path(__file__).resolve().parents[1] / 'fixtures/comparison-selected-reference-gap-v1.json'
VERSION = 'comparison-selected-reference-gap-1'


@lru_cache(maxsize=1)
def registry():
    body = PATH.read_bytes()
    if len(body) > 65536:
        raise ValueError('Bounded reference gap registry required')
    value = json.loads(body)
    if (value.get('version') != VERSION or len(value.get('records', [])) > 16 or
            value.get('sha256') != digest({k:v for k,v in value.items() if k != 'sha256'})):
        raise ValueError('Sealed reference gap registry required')
    return value


def assessment(q):
    """Exact historical attachment only. Candidate prices cannot become a ref."""
    if q.get('sharp_reference') is not None or not q['provenance'].get('real_source'):
        return None
    for row in registry()['records']:
        if row['observation'] == observation(q) and row['selection'] == q['binding']['selection']:
            result=deepcopy(row['assessment'])
            from app.collection.current_occurrence import selected_proof
            proof=selected_proof()
            result['prospective_review']=dict(
                status='accepted_prospective_manual_review',
                occurrence_id=proof['event']['game_id'],
                evidence_sha256=proof['evidence'][0]['sha256'],
                effective_from=proof['applicability']['start'],
                effective_until=proof['applicability']['end'],
                reviewer='Codex DATA engineer; recorded review, no human signoff',
                venue='Tottenham Hotspur Stadium; NFL2026 regular-season Week5',
                historical_applicability=False,
                reference_prices_acquired=False,
                rules='Published NFL Game-period includes overtime; two-way tie void; exceptional rules differ',
                rule_version='Unversioned official page observed October9; no past effective date established')
            return result
    return None
