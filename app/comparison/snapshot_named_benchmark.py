"""Select captured named-book witnesses without substituting another source."""
from copy import deepcopy

from app.collection.current_benchmark import attach
from app.dashboard.current_contract import identity
from app.storage.store import hashed


def references(quotes, retained, settings):
    venue=settings['benchmark_venue']
    if venue=='pinnacle':return retained
    out=[]
    for row in quotes:
        record=row.get('original_record')
        if row.get('venue')!=venue or not record:continue
        q=record['quote']
        out.append(dict(id=hashed(q['source']),venue=venue,original_record=record,
            market=record['market_identity'],game_key=row['game_key'],
            original=q['original'],source=q['source'],times=q['times'],selection=record['selection']))
    return out


def bind(quotes, refs, settings):
    """Reuse the aggregate's exact semantic, receipt and signed-line pairing.

    Native prices need the separately supported snapshot identity path; no
    opaque provider ID, team label or missing scoring rule supplies that link.
    """
    venue=settings['benchmark_venue']
    if venue=='pinnacle':return quotes
    selected=[r['original_record'] for r in refs if r.get('original_record') and r['original_record'].get('verified') and r.get('source',{}).get('provider')=='the_odds_api']
    records=[deepcopy(r['original_record']) for r in quotes if r.get('original_record') and r['original_record'].get('verified') and r.get('source',{}).get('provider')=='the_odds_api']
    attach(records,selected,venue=venue)
    index={hashed(r['quote']['source']):r['quote'].get('sharp_reference') for r in records}
    out=[]
    for row in quotes:
        q=dict(row);out.append(q)
        q['reference']=None;q['benchmark_quote']=None
        if row.get('source',{}).get('provider')!='the_odds_api':continue
        ref=deepcopy(index.get(hashed(row['source'])))
        if not ref:continue
        ref['selection_digest']=identity('binding',row['binding']['selection'])
        q['reference']=ref
        q['benchmark_quote']=dict(id=row['quote_id'],revision=row.get('quote_revision',1),
            venue=row['venue'],source=row['source'],times=row['times'],original=row['original'],
            binding=row['binding'],display=row['common_odds'],state=row.get('source_state'),sharp_reference=ref)
    return out


def selected_references(selection, original, references):
    benchmark = selection.get("snapshot_benchmark")
    if benchmark:
        # Source IDs outlive individual observations. Match both sides to
        # the exact frame that supplied the selected probability.
        ids = benchmark.get("ids", [])
        if (
            len(ids) != 2 or ids[0] == ids[1]
            or not all(benchmark.get(k) for k in ("bookmaker", "received_at", "sha256"))
            or not all(len(benchmark.get(k) or []) == 2 for k in ("odds", "source_at", "provider_clocks"))
        ):
            return []
        pair = [None, None]
        for candidate in references:
            if candidate["id"] not in ids:
                continue
            side = ids.index(candidate["id"])
            quote = (candidate.get("original_record") or {}).get("quote", {})
            times = quote.get("times", {})
            if (
                quote.get("venue") == benchmark["bookmaker"]
                and quote.get("provenance", {}).get("sha256") == benchmark["sha256"]
                and times.get("received_at") == benchmark["received_at"]
                and times.get("source_at") == benchmark["source_at"][side]
                and quote.get("provider_clocks") == benchmark["provider_clocks"][side]
                and quote.get("original", {}).get("value") == benchmark["odds"][side]
            ):
                if pair[side] is not None:
                    return []
                pair[side] = candidate
        return pair if all(pair) else []
    ref = selection.get("reference")
    record = original.get("original_record")
    if not ref or not record:
        return []
    from app.collection.current_benchmark import key
    from app.comparison.event_links import semantic_market, occurrence_sport

    # Reconstruct only the same source receipt and market used by attach().
    market = semantic_market(record)
    market["sport"]=occurrence_sport(market["competition"],market["sport"])
    source = record["quote"]["source"]
    routes = {}
    for candidate in references:
        witness = candidate.get("original_record")
        if not witness:
            continue
        q = witness["quote"]
        # Execution bundles project event IDs; reference witnesses retain the
        # provider's event ID. Require the exact provider occurrence on both.
        if any(q["source"][k] != source[k] for k in ("provider", "native_event_id")):
            continue
        if q["venue"] != ref.get("bookmaker"):
            continue
        witness_market = semantic_market(witness)
        witness_market["sport"]=occurrence_sport(witness_market["competition"],witness_market["sport"])
        if (
            q["provenance"]["sha256"] == ref.get("sha256")
            and q["times"]["received_at"] == ref.get("received_at")
            and witness_market == dict(market, event=witness_market["event"])
        ):
            alternate = q["source"]["native_market_id"].startswith("alternate:")
            routes.setdefault(alternate, []).append(candidate)
    matches = []
    for group in routes.values():
        if len(group) != 2:
            continue
        pair = sorted(group, key=lambda r: key(r["original_record"]))
        if (
            [r["original"]["value"] for r in pair] == ref["odds"]
            and [r["times"]["source_at"] for r in pair] == ref["source_at"]
            and key(pair[ref["selected"]]["original_record"])
            == key(dict(record, market_identity=pair[0]["market"]))
        ):
            matches.append(pair)
    return matches[0] if len(matches) == 1 else []
