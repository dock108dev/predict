"""Authored transport-sized frames; no provider, owner SQL or financial guesses."""
from copy import deepcopy
from unittest import TestCase
from app.storage.latest_board import bounded_page
from app.storage.store import encoded
from app.comparison.calculation_availability import summary

CAP=8*1024*1024
class SlateBytePages(TestCase):
    def frame(self,count):
        games=[dict(game_key=str(i),title='Authored '+str(i),catalog_fact='c'*4500) for i in range(count)]
        boards=[dict(game_key=str(i),availability=summary([],evaluated=False),
            original=dict(value='2.94',native_side='buy_yes',source_at='2026-10-23T00:08:00Z'),
            facts='x'*(210000+(i%3)*10000)) for i in range(count)]
        return dict(games=games,read_token='fixed',read_revision='fixed',read_at='2026-10-23T00:08:01Z',policy={'revision':'fixed'}),boards

    def test_measured_scale_and_neighboring_pages_keep_every_fact_and_game(self):
        for count in (49,50,51,101):
            with self.subTest(count=count):
                header,boards=self.frame(count);before=deepcopy(boards);offset=0;collected=[];sizes=[]
                self.assertGreater(len(encoded(dict(header,boards=boards[:50]))),10232310)
                while True:
                    value,size=bounded_page(header,boards[offset:offset+50],[],offset=offset,limit=50,evaluated=False)
                    sizes.append(size);self.assertLessEqual(size,CAP);self.assertEqual(size,len(encoded(value)))
                    self.assertEqual(value['read_token'],header['read_token']);collected+=value['boards']
                    self.assertGreater(value['coverage']['returned_games'],0)
                    if value['coverage']['complete']:break
                    offset=value['coverage']['next_offset']
                self.assertEqual(collected,before)
                self.assertEqual(len({b['game_key'] for b in collected}),count)
                self.assertGreater(len(sizes),1)

    def test_error_at_byte_boundary_remains_part_of_coverage(self):
        header,boards=self.frame(50);missing=boards.pop(19)
        error=dict(game_key=missing['game_key'],reason='calculation_failed')
        offset=0;seen=[];failures=[]
        while True:
            keys={g['game_key'] for g in header['games'][offset:offset+50]}
            value,_=bounded_page(header,[b for b in boards if b['game_key'] in keys],
                [error] if error['game_key'] in keys else [],offset=offset,limit=50,evaluated=False)
            seen += [b['game_key'] for b in value['boards']]+[e['game_key'] for e in value['errors']]
            failures += value['errors']
            if value['coverage']['complete']:break
            offset=value['coverage']['next_offset']
        self.assertEqual(set(seen),{g['game_key'] for g in header['games']})
        self.assertEqual(len(seen),50);self.assertEqual(failures,[error])

    def test_exact_byte_boundary_empty_and_unrepresentable_game(self):
        header,boards=self.frame(2)
        value,size=bounded_page(header,boards,[],offset=0,limit=50,evaluated=False)
        boards[1]['facts']+='x'*(CAP-size)
        value,size=bounded_page(header,boards,[],offset=0,limit=50,evaluated=False)
        self.assertEqual(size,CAP);self.assertTrue(value['coverage']['complete'])
        boards[1]['facts']+='x'
        value,size=bounded_page(header,boards,[],offset=0,limit=50,evaluated=False)
        self.assertEqual(value['coverage']['next_offset'],1)
        tail,_=bounded_page(header,boards[1:],[],offset=1,limit=50,evaluated=False)
        self.assertTrue(tail['coverage']['complete']);self.assertEqual(tail['boards'],boards[1:])
        boards[0]['facts']='x'*CAP
        with self.assertRaisesRegex(ValueError,'slate_response_byte_capacity'):
            bounded_page(header,boards,[],offset=0,limit=50,evaluated=False)
        empty,_=bounded_page(dict(header,games=[]),[],[],offset=0,limit=50,evaluated=False)
        self.assertTrue(empty['coverage']['complete']);self.assertEqual(empty['coverage']['returned_games'],0)
