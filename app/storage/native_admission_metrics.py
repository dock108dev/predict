"""Per-transaction native top-price changes, distinct from visible publication."""
from app.comparison.source_clock import assess
from .store import stamp


class MaterialRows:
    def __init__(self):
        self.before={}
        self.accepted={}
        self.order_refusals=0
        self.contract_inserts=0
        self.contract_updates=0
        self.scope_retirements=0
        self.scope_offer_retirements=0

    def observe(self,prepared,old,event):
        key=prepared['contract_id']
        if key not in self.before:
            self.before[key]=None if not old else (old['price_value'],old['price_units'],old['quantity_units'])
        self.accepted[key]=(prepared,event['scheduled_start'])

    def counts(self,at):
        instant=stamp(at)
        counts=dict(initial=0,changed=0,same=0,missing=0,order_refusals=self.order_refusals,
                    material_in_window=0,fresh_material=0,contract_inserts=self.contract_inserts,
                    contract_updates=self.contract_updates,scope_retirements=self.scope_retirements,
                    scope_offer_retirements=self.scope_offer_retirements)
        for key,(row,start) in self.accepted.items():
            if row['missing']:
                counts['missing']+=1
                continue
            quote=row['quote']
            original=quote['original']
            price=(original['value'],original['units'],original['quantity_units'])
            prior=self.before[key]
            kind='initial' if prior is None else 'same' if prior==price else 'changed'
            counts[kind]+=1
            if kind=='same' or not 0<=(stamp(start)-instant).total_seconds()<72*3600:continue
            counts['material_in_window']+=1
            clock=dict(quote,times=dict(received_at=row['received_at'],source_at=row['source_at']),
                       freshness_policy=dict(maximum_age_seconds=30))
            if not assess(clock,instant)['reasons']:counts['fresh_material']+=1
        return counts
