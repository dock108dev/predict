"""Indexed lookup preserves the frozen resolver's identities and provenance."""
import ast
import unittest
from pathlib import Path
from app.normalization.registry import Registry
from app.normalization.names import name_key
from app.normalization.college_registry import aggregate_registry

class RegistryIndex(unittest.TestCase):
    def test_original_and_indexed_resolution_agree_on_retained_alias_contexts(self):
        original = Path(__file__).parent/'fixtures/registry-resolve-baseline.py'
        # Load the exact portable pre-index method; no ignored/frozen checkout dependency.
        tree = ast.parse(original.read_text())
        method = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='resolve')
        namespace = {'name_key':name_key}
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(original),'exec'),namespace)
        legacy = type('OriginalRegistry',(Registry,),{'resolve':namespace['resolve']})
        indexed = aggregate_registry(); before = legacy(__import__('json').loads(indexed.to_json()))
        cases = [('team',name,dict(league=league,venue='the_odds_api')) for league,name in (
            ('NFL','Seattle Seahawks'),('NFL','Denver Broncos'),('NFL','JAC'),('MLB','New York'),
            ('NBA','Dallas'),('NCAAF','Alabama'),('NCAAB','Duke'),('NFL','Invented'))]
        cases += [('team',name,{}) for name in ('Giants','DAL','Los Angeles','é','49ers',None)]
        cases += [('league',name,{}) for name in ('NFL','National Football League','WNBA','NCAAF','NCAAB')]
        for row in indexed.native.values():
            cases.append((row['kind'],None,dict(league=row.get('league'),venue=row['venue'],environment=row['environment'],native_id=row['native_id'])))
        for kind,name,context in cases:
            with self.subTest(kind=kind,name=name,context=context):
                self.assertEqual(indexed.resolve(kind,name,**context),before.resolve(kind,name,**context))
