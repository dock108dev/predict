"""Catalog dependencies: native image authority and derived metadata are separate."""
from app.dashboard.session_projection import stable
from .current_native_catalog import book_material,native_material


def dependencies(inventory):
    result={}
    for source,catalog in inventory.items():
        events={e['id']:e for e in catalog['events']}
        native_events={key:native_material(source,event,event=True) for key,event in events.items()}
        # Capture/provenance changes alone do not change an admitted calculation.
        # Unknown fields remain dependencies; actual native terms stay guarded by
        # the existing semantic projection, including eligibility and unknowns.
        event_values={key:{k:v for k,v in event.items() if k not in (
            '_native','native_metadata','provenance','occurrences','market_ids',
            'market_discovery','embedded_market_packaging_reference')}
            for key,event in events.items()}
        from app.storage.schedule_metadata import witness
        for key,event in events.items():
            proof=witness(event)
            if proof:
                # A later receipt of the same validated schedule is new
                # provenance, not new calculation inputs. Keep the full proof
                # in the inventory; future book updates retain their own proof.
                event_values[key]['schedule_metadata']={k:v for k,v in proof.items()
                    if k not in ('revision','received_at','proofs','observed_no_later_than')}
        for market in catalog['markets']:
            event=events.get(market['event_id'])
            if event is None:continue
            native=book_material(source,event,market,event_material=native_events[event['id']])
            binding=dict(market.get('v1_raw_binding') or {})
            binding.pop('sha256',None);binding.pop('native_metadata_sha256',None)
            if binding.get('source_predicate'):
                binding['source_predicate']={k:v for k,v in binding['source_predicate'].items() if k!='native_metadata_sha256'}
            if binding.get('locator'):
                locator=dict(binding['locator'])
                if isinstance(locator.get('original'),dict):
                    locator['original']=native_material(source,dict(_native=locator['original']))
                binding['locator']=locator
            fields={k:v for k,v in market.items() if k not in (
                '_native','native_metadata','provenance','occurrences','v1_raw_binding')}
            if fields.get('source_predicate'):
                fields['source_predicate']={k:v for k,v in fields['source_predicate'].items() if k!='native_metadata_sha256'}
            result[(source,event['id'],market['id'])]=(native,stable([native,event_values[event['id']],fields,binding]))
    return result


def changes(previous,current):
    old=dependencies(previous);new=dependencies(current)
    retained={key for key in old.keys()&new.keys() if old[key][0]==new[key][0]}
    return dict(retained=retained,withdraw=set(old)-retained,
                refresh={key for key in retained if old[key][1]!=new[key][1]})
