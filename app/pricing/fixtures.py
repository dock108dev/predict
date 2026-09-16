"""E3 reuses the E2 invented NFL event and receipt/enrichment path."""
import base64
from hashlib import sha256
from app.edge_contracts import dumps
from app.reference.fixtures import payload, before, terms, source, assessment
from app.reference.records import Receipt, request_metadata, packed, as_of
from app.reference.enrichment import enrich
from .baseline import Target, calculate


def target(**changes):
    args = dict(venue='kalshi', terms_json=dumps(terms()), outcome=terms().outcomes[0],
                known_at=before(120), effective_at=before(120),
                evidence=('synthetic:existing NFL target terms assumption',))
    args.update(changes)
    return Target(**args)


def receipt(body=None, identity='e3-r1', at=None, session='synthetic-e3', status=200):
    body = payload() if body is None else body
    return Receipt(id=identity, session_id=session, received_at=at or before(), request_started_at=at or before(),
        body_b64=base64.b64encode(body).decode(), body_sha256=sha256(body).hexdigest(), status=status,
        request_json=packed(request_metadata()), headers=())


def records(r=None, src=None, assessed=None):
    r, src, assessed = r or receipt(), src or source(), assessed or assessment()
    return (src, r, enrich(r, src, assessed, revision_id=r.id + '-enrichment'))


def example():
    first = records()
    newer = receipt(body=b'{"synthetic":"rejected snapshot"}', identity='e3-r2', at=before(50))
    history = (*first, newer, enrich(newer, first[0], assessment(), revision_id='e3-rejected'))
    estimates = [calculate(as_of(history, c), target=target(), cutoff=c, estimated_at=c)
                 for c in (before(55), before(45))]
    return history, estimates
