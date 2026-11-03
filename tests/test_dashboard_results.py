"""Dashboard contract oracle; authored values do not qualify live finance."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
from unittest import TestCase
from app.storage.dashboard_results import project, rank, in_window
from app.storage.store import stamp

class DashboardContract(TestCase):
    def test_complete_window_edges_and_unknown_schedule(self):
        now=stamp('2026-10-31T00:00:00Z');end=now+timedelta(hours=72)
        for at,expected in ((now,True),(end,False),(now-timedelta(microseconds=1),False),(end-timedelta(microseconds=1),True)):
            self.assertEqual(in_window(dict(start_at=at.isoformat()),now,end),expected)
        self.assertFalse(in_window({},now,end))
        self.assertFalse(in_window(dict(start_at='unknown'),now,end))

    def test_global_exact_order_including_late_page_zero_negative_and_ties(self):
        rows=[]
        for i in range(130):
            value=str(-130+i)
            rows.append((dict(game_key=f'g{i:03}',start_at='2026-11-01T00:00:00Z'),
                dict(quote_id=str(i),financial_metrics=dict(buffered_return_percent=value))))
        rows[-1][1]['financial_metrics']['buffered_return_percent']='0'
        rows[-2][1]['financial_metrics']['buffered_return_percent']='0'
        actual=rank(rows,'ev')
        oracle=sorted(rows,key=lambda e:(-Fraction(e[1]['financial_metrics']['buffered_return_percent']),e[0]['game_key']))
        self.assertEqual(actual,oracle)
        self.assertEqual([e[0]['game_key'] for e in actual[:3]],['g128','g129','g127'])

    def test_projection_never_promotes_conditional_or_hypothetical_and_preserves_refusals(self):
        base=dict(rows=[],prices=[],availability=dict(total_results=0,causes=[]))
        rows=[dict(quote_id=str(i),financial_metrics=m,availability={}) for i,m in enumerate([
            dict(buffered_ev_usd='0',buffered_return_percent='0'),
            dict(buffered_ev_usd='-2',buffered_return_percent='-1/3'),
            dict(conditional_buffered_ev_usd='10',conditional_buffered_return_percent='10'),
            dict(buffered_ev_usd='3',buffered_return_percent='3')])]
        rows[-1]['modeled_basis']={'hypothetical':True}
        facts=dict(selected_frame='private-captured-evidence',boards=dict(ev=dict(base,rows=rows),arbs=dict(base,availability=dict(total_results=2,causes=[dict(code='fees_unbound',affected_results=2)]))))
        original=deepcopy(facts);out=project(facts)
        self.assertEqual(facts,original)
        self.assertNotIn('selected_frame',out)
        self.assertEqual([r['quote_id'] for r in out['boards']['ev']['rows']],['0','1'])
        self.assertEqual(out['boards']['arbs']['dashboard_counts']['refused_units'],2)
        self.assertEqual(out['boards']['arbs']['dashboard_counts']['total'],0)
