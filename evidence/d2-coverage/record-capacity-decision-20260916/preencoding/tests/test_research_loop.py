import copy
from decimal import Decimal, localcontext
from fractions import Fraction as F
import tempfile
import unittest
from unittest.mock import patch
from app.reference import research_loop as r
from app.pricing.baseline import devig
from tests.test_public_page import BODY, META
from hashlib import sha256
import base64

class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deps = dict(html_base64=base64.b64encode(BODY).decode(), capture=dict(META, sha256=sha256(BODY).hexdigest()))
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.folder=self.tmp.name
    def save(self, **kw): return r.save(self.folder,self.deps,**kw)
    def test_exact_real_pair(self):
        c=r.calculation(self.deps); a,b=c['page']['sides']
        self.assertEqual(a['decimal_odds_exact'],'14/5'); self.assertEqual(b['decimal_odds_exact'],'159/109')
        self.assertEqual(a['implied_probability_exact'],'5/14'); self.assertEqual(b['implied_probability_exact'],'109/159')
        # independent rational: sum 2321/2226, overround 95/2226, pDET 795/2321.
        with localcontext() as ctx:
            ctx.prec=50
            self.assertEqual(Decimal(a['probability']),(Decimal(795)/2321).quantize(Decimal('1e-18')))
            self.assertLess(abs(F(c['arithmetic']['overround'])-F(95,2226)), F(1,10**48))
        self.assertFalse(c['live_qualified']); self.assertIsNone(c['page']['bookmaker_updated_at'])
        self.assertIn('unknown',c['label'])
    def test_reversal_and_invalid_identity(self):
        import app.reference.public_page as p
        original=p.parse(BODY,self.deps['capture'],event_id='32144330')
        with patch.object(r,'parse',return_value=dict(original,sides=list(reversed(original['sides'])))):
            c=r.calculation(self.deps)
            self.assertEqual(c['page']['sides'][0]['team'],'Buffalo Bills')
            self.assertEqual(c['page']['sides'][0]['probability'],'0.657475226195605343')
        for raw in (BODY.replace(b'alt="Buffalo Bills"',b'alt="Wrong Team"'), BODY.replace(b'+180',b'NaN',1)):
            d=dict(html_base64=base64.b64encode(raw).decode(),capture=dict(META,sha256=sha256(raw).hexdigest()))
            with self.assertRaises(ValueError):r.calculation(d)
    def example(self, p='0.538461538461538462', **kw):
        args=dict(teams=['A','B'],target_team='A',levels=[dict(price='.54',quantity='6'),dict(price='.55',quantity='4')],quantity='10',entry_fee='.16',later_fee='0',payout_win='1',payout_lose='0',assumption='synthetic fixed total charge; not a venue schedule')
        args.update(kw);return r.conditional(p,**args)
    def test_independent_plan_and_signs(self):
        self.assertEqual(devig([Decimal('1.80'),Decimal('2.10')])['probabilities'][0], '0.538461538461538462')
        e=self.example();self.assertEqual(Decimal(e['expected_profit']),Decimal('-.215384615384615380'))
        self.assertEqual(F(e['cost']),F(136,25)); self.assertEqual(F(e['cash']),F(28,5))
        self.assertLess(abs(F(e['expected_profit'])-F(-14,65)),F(1,10**17))
        for p,sign in [('0.7',1),('0.56',0),('0.2',-1)]:
            v=Decimal(self.example(p)['expected_profit']);self.assertEqual((v>0)-(v<0),sign)
        for changes in (dict(entry_fee=None),dict(later_fee=None),dict(quantity='11'),dict(payout_win=None)):
            self.assertIsNone(self.example(**changes)['expected_profit'])
        self.assertIsNone(e['unconditional_ev'])
    def test_save_reopen_corrections_and_time(self):
        a=self.save();self.assertEqual(r.reopen(self.folder,a['id']),a)
        b=self.save(supersedes_id=a['id'],reason='append corrected analysis')
        self.assertEqual(r.get(self.folder,a['id']),a);self.assertEqual(b['dependencies'],self.deps)
        with self.assertRaises(ValueError):self.save(cutoff='2026-09-16T01:07:35Z')
        with patch.object(r,'now',return_value='2026-09-18T00:14:30Z'):
            late=self.save(primary=True)
        self.assertEqual(late['evaluation_designation'],'retrospective')
    def test_annotations_scores_and_repeats(self):
        p=self.save(primary=True,synthetic_clock='2026-09-17T23:50:00Z')
        self.save(synthetic_clock='2026-09-17T23:51:00Z')
        with self.assertRaises(ValueError):self.save(primary=True)
        base=dict(source='synthetic:test',published_at='2026-09-18T04:00:00Z',observed_at='2026-09-18T04:01:00Z',final=True,synthetic=True)
        a=r.annotate(self.folder,p['id'],'sporting',dict(base,result='Detroit Lions',score='24-21'))
        e=r.evaluate(self.folder);self.assertEqual(len(e['scores']),1);self.assertEqual(e['prospective_count'],0)
        with localcontext() as ctx:
            ctx.prec=100
            prob=Decimal('0.342524773804394657')
            self.assertEqual(Decimal(e['scores'][0]['brier']),(prob-1)**2)
        self.assertEqual(e['settlement_annotations'],[])
        r.annotate(self.folder,p['id'],'settlement',dict(base,contract_id='synthetic:yes',basis='separate invented settlement',payout_per_contract='.5'))
        self.assertEqual(r.evaluate(self.folder)['scores'],e['scores'])
        with self.assertRaises(ValueError):r.annotate(self.folder,p['id'],'sporting',dict(base,result='tie',score='21-21'))
        r.annotate(self.folder,p['id'],'sporting',dict(base,result='tie',score='21-21'),supersedes_id=a['id'],reason='synthetic correction')
        self.assertEqual(r.evaluate(self.folder)['scores'],[])
        self.assertIn('tie',[x['reason'] for x in r.evaluate(self.folder)['excluded']])
    def test_saved_target_is_retrospective_and_oriented(self):
        from pathlib import Path
        c=r.compare_saved_target(self.deps,Path('evidence/multi-game/sessions/5c9b7dca-a813-4d77-80f5-0691d06068eb'))
        self.assertEqual(c['target_contract']['team'],'Buffalo Bills')
        self.assertEqual(c['target_probability'],'0.657475226195605343')
        self.assertGreater(r.timestamp(c['reference_retrieved_at']),r.timestamp(c['target_cutoff']))
        self.assertFalse(c['prospective_evaluation_eligible']);self.assertIsNone(c['conditional_ev'])
        self.assertEqual(sum(F(f['quantity']) for f in c['target_diagnostics']['fills']),10)
    def test_prospective_and_unresolved_selection(self):
        with patch.object(r,'now',return_value='2026-09-17T23:50:00Z'):
            old=self.save(primary=True)
        self.assertEqual(old['evaluation_designation'],'retrospective')
        from pathlib import Path
        for f in Path(self.folder).glob('*.json'): f.unlink()
        deps=copy.deepcopy(self.deps);deps['capture']['retrieved_at']='2026-09-17T23:49:59Z'
        with patch.object(r,'now',return_value='2026-09-17T23:50:00Z'):
            p=r.save(self.folder,deps,primary=True)
        self.assertEqual(p['evaluation_designation'],'prospective_primary')
        self.assertEqual(r.evaluate(self.folder)['excluded'][0]['reason'],'unresolved')
        base=dict(source='synthetic test of real record validation',published_at='2026-09-18T04:00:00Z',observed_at='2026-09-18T04:01:00Z',final=True,synthetic=False,result='Buffalo Bills',score='21-24')
        with patch.object(r,'now',return_value='2026-09-18T04:02:00Z'):
            r.annotate(self.folder,p['id'],'sporting',base)
        self.assertEqual(r.evaluate(self.folder)['prospective_count'],1)
        with self.assertRaises(ValueError):self.save(synthetic_clock='2026-09-18T04:00:00Z')

    def test_integrity_and_failed_save(self):
        p=self.save()
        from pathlib import Path
        f=Path(self.folder)/(p['id']+'.json'); f.write_text(f.read_text().replace('proportional-devig-1','changed'))
        with self.assertRaises(ValueError):r.reopen(self.folder,p['id'])
        f.unlink()
        with patch.object(r,'append',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):self.save()

if __name__=='__main__':unittest.main()
