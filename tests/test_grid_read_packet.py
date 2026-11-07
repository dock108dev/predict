from app.storage.grid_read_packet import pack
from app.storage.slate_reads import CapturedReads
from app.storage.store import encoded


def test_packet_preserves_originals_and_independent_dependency_proof():
    reads=CapturedReads(resource_bytes=lambda:0)
    facts=dict(selected_frame='exact captured input'*3000,publication_dependencies={'selector':{'events':['one']}},boards={'odds':{'old':True}})
    row=dict(game_key='one',dependency_revision='d',economic_revision='e',calculated_at='t',facts=facts)
    grid={'prices':[{'original':{'value':'0.5400'},'quote_id':'q'}]}
    packet=pack(row,grid)
    record=reads.join_record('one',packet,{'offers':{'o':{'revision':'before'}}})
    value=reads.decode(record)
    import json
    assert json.loads(value['row']['_facts_text'])=={k:v for k,v in facts.items() if k!='boards'}
    assert json.loads(value['row']['_board_text'])==grid
    assert value['_proof']['offers']['o']['revision']=='before'
    assert reads.freeze(record) is record
    # Selection goes directly to the indexed record, never decoding unrelated games.
    frame=reads.capture({'games':[{'game_key':'other'},{'game_key':'one'}]},[b'not-json',record],context='ordinary',authority='a')
    selected,token=reads.selection(frame.token,'one')
    assert selected['facts']['selected_frame']==facts['selected_frame']
    assert token!=frame.token


def test_routing_slug_does_not_copy_or_mutate_native_catalog():
    from unittest.mock import patch
    from tests.test_current_native import us_market
    from app.adapters.polymarket_us import market_slug,next_market_data
    market=us_market();expected=next_market_data(market)['slug']
    with patch('app.adapters.polymarket_us.deepcopy',side_effect=AssertionError('routing copied evidence')):
        assert market_slug(market)==expected
    with patch('app.adapters.polymarket_us._market_index',side_effect=AssertionError('redecoded owned route')):
        assert market_slug(market) == expected
    assert next_market_data(market)['slug']==expected


def test_completed_composite_keeps_exact_originals_without_decoding_unselected_packets():
    from unittest.mock import patch
    reads=CapturedReads(resource_bytes=lambda:0)
    row=dict(game_key='one',dependency_revision='d',economic_revision='e',calculated_at='t',facts=dict(selected_frame='exact',boards={}))
    record=reads.join_record('one',pack(row,{'prices':[]}),{'offers':{'old':'proof'}})
    frame=reads.capture({'games':[{'game_key':'one'}]},[record],context='ordinary',authority='a')
    decode=reads.decode
    def pointer_only(packet):
        value=decode(packet)
        # Completion may decode its small pointer envelope to drop rendered
        # prices, but must not hydrate the independently retained Originals.
        assert '_facts_blob' in value and '_facts_text' not in value
        return value
    with patch.object(reads,'decode',side_effect=pointer_only):
        reads.account(frame,offset=0,limit=5,size=100,complete=True)
    assert '_proof' not in reads.decode(frame.records[0])
    selected,_=reads.selection(frame.token,'one')
    assert selected['facts']['selected_frame']=='exact'


def test_catalog_compaction_preserves_distinct_meanings_and_original_count():
    from app.storage.latest_board import compact_catalog_game
    game={'game_key':'one','matches':[
        {'revision':'a','status':'matched','reason':None},
        {'revision':'b','status':'matched','reason':None},
        {'revision':'c','status':'rejected','reason':'period'}]}
    compact=compact_catalog_game(game)
    assert compact['match_count']==3
    assert compact['matches']==[{'status':'matched','reason':None},
                               {'status':'rejected','reason':'period'}]
    assert compact_catalog_game(compact)==compact
    assert len(game['matches'])==3 and game['matches'][0]['revision']=='a'


def test_odds_packet_does_not_duplicate_independently_owned_financial_units():
    import json
    row=dict(game_key='one',dependency_revision='d',economic_revision='e',calculated_at='t',
        facts=dict(selected_frame='exact parent Original',observation_context={'context_id':'price'},
            publication_dependencies={'selector':{'events':['one']}},
            result_units={'unit':{'facts':{'selected_frame':'financial evidence'*10000}}},
            result_unit_inventory=[{'id':'unit'}],dashboard_boards={'ev':{'rows':[]}},boards={}))
    reads=CapturedReads(resource_bytes=lambda:0)
    decoded=reads.decode(pack(row,{'prices':[]}))
    facts=json.loads(decoded['_facts_text'])
    assert facts['selected_frame']=='exact parent Original'
    assert facts['observation_context']=={'context_id':'price'}
    assert 'result_units' not in facts and 'dashboard_boards' not in facts
    assert row['facts']['result_units']['unit']['facts']['selected_frame']=='financial evidence'*10000
