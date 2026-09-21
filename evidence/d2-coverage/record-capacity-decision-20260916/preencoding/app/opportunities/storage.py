"""Immutable input objects and per-evaluation links over explicit connections."""
from pathlib import Path
from hashlib import sha256
from app.reference.records import packed
from app.pricing.storage import FairPriceStore
from app.fees.engine import digest
from .service import replay, restore


class OpportunityStore:
    def __init__(self, connection):
        self.db=connection
        self.fair=FairPriceStore(connection)
        self.foundation=self.fair.foundation

    def save(self, audit):
        replay(audit)
        data=audit.data
        with self.db.transaction():
            estimate=self.fair.get(data['estimate_id'])
            if estimate.export()!=data['inputs']['estimate']:
                raise ValueError('persisted E3 dependency differs')
            for kind, value in data['inputs'].items():
                body=packed(value)
                self.foundation.immutable('opportunity_dependency',dict(id=digest(value),payload=body,payload_sha256=sha256(body.encode()).hexdigest()),['id'])
            body=audit.export()
            self.foundation.immutable('opportunity_audit',dict(id=audit.id,estimate_id=estimate.id,
                as_of=data['inputs']['as_of'],evaluated_at=data['inputs']['evaluated_at'],version=data['version'],payload=body,
                payload_sha256=sha256(body.encode()).hexdigest()),['id'])
            for kind, value in data['inputs'].items():
                self.foundation.immutable('opportunity_input',dict(audit_id=audit.id,kind=kind,dependency_id=digest(value)),['audit_id','kind'])

    def get(self, identity):
        row=self.db.execute('SELECT * FROM opportunity_audit WHERE id=%s',(identity,)).fetchone()
        if not row or sha256(row['payload'].encode()).hexdigest()!=row['payload_sha256']:
            raise ValueError('missing/corrupted opportunity')
        audit=restore(row['payload']); data=audit.data
        if audit.id!=identity or row['estimate_id']!=data['estimate_id']:
            raise ValueError('opportunity durable identity mismatch')
        if self.fair.get(data['estimate_id']).export()!=data['inputs']['estimate']:
            raise ValueError('durable E3 dependency mismatch')
        links=self.db.execute('SELECT i.kind,d.* FROM opportunity_input i JOIN opportunity_dependency d ON d.id=i.dependency_id WHERE i.audit_id=%s',(identity,)).fetchall()
        if len(links)!=len(data['inputs']): raise ValueError('missing opportunity dependency')
        for link in links:
            value=data['inputs'].get(link['kind'])
            if link['kind'] not in data['inputs'] or link['id']!=digest(value) or link['payload']!=packed(value) or sha256(link['payload'].encode()).hexdigest()!=link['payload_sha256']:
                raise ValueError('changed opportunity dependency')
        return audit

    def evaluate(self, estimate_id, inputs):
        """Operational entry point always obtains a replay-verified durable estimate."""
        from .service import evaluate
        inputs={**inputs,'estimate':self.fair.get(estimate_id).export()}
        audit=evaluate(inputs)
        self.save(audit)
        return audit

    def export(self, identity, path):
        body=self.get(identity).export(); Path(path).write_text(body)
        return sha256(body.encode()).hexdigest()

    def restore(self, path):
        # Restore full reference history and exact E3 estimates first.
        audit=restore(Path(path).read_text()); self.save(audit); return audit
