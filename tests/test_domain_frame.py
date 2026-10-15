"""Bounded domain-fact frames preserve exact old logical bytes and stable slots."""
import copy
from hashlib import sha256
import json
import unittest
from unittest.mock import patch
from app.storage import domain_frame as f

class DomainFrames(unittest.TestCase):
    def example(self):
        return dict(game_key='game1',policy=dict(revision='policy-1',fee='0.0000',unknown=None),model_versions={'fees':'v1'},state=dict(comparison_profiles=dict(version='shared-2',templates={'t1':{'version':'t1','kind':'fee','payload':{'rate':'0.0125','null':None}}},bindings={}),event={'id':'game1','title':'Città vs NYC','participants':['a','b']},events=[{'id':'financial','groups':[{'net':'2.2100'}]}]),inventory=dict(events=[{'id':'g'}],markets=[{'native':'contract'}]),source_at='2026-10-14T00:00:00.000000001Z',untouched=None)
    def test_only_semantic_facts_are_extracted_and_original_null_is_retained(self):
        value=self.example();before=copy.deepcopy(value);raw=f.canonical(value);descriptor,facts=f.extract(raw);frame,sizes=f.descriptor(descriptor)
        self.assertEqual(value,before);self.assertEqual(frame['data']['untouched'],None)
        paths=[v[0] for v in frame['facts']]
        self.assertIn(['policy'],paths);self.assertIn(['model_versions'],paths);self.assertIn(['state','comparison_profiles','templates','t1'],paths);self.assertIn(['state','event'],paths);self.assertNotIn(['state','events',0],paths)
        self.assertEqual(f.expand(descriptor,facts,len(raw),sha256(raw).hexdigest()),raw)
    def test_versioned_facts_are_global_content_ids_across_games_and_changed_clocks(self):
        first=self.example();second=copy.deepcopy(first);second['game_key']='game2';second['state']['event']['id']='game2';second['source_at']='2026-10-14T00:00:00.000000002Z'
        one=f.extract(f.canonical(first));two=f.extract(f.canonical(second))
        policy=sha256(f.canonical(first['policy'])).hexdigest();template=sha256(f.canonical(first['state']['comparison_profiles']['templates']['t1'])).hexdigest()
        self.assertEqual(one[1][policy],two[1][policy]);self.assertEqual(one[1][template],two[1][template])
    def test_fact_hash_size_missing_and_noncanonical_bytes_refuse(self):
        raw=f.canonical(self.example());descriptor,facts=f.extract(raw);key=next(iter(facts))
        for changed in ({},dict(facts,**{key:facts[key]+b' '}),dict(facts,**{key:b'null'})):
            with self.assertRaises(ValueError):f.expand(descriptor,changed,len(raw),sha256(raw).hexdigest())
        self.assertIsNone(f.extract(json.dumps(self.example(),ensure_ascii=False).encode()))
        with self.assertRaises(ValueError):f.parse(b'{"a":1,"a":1}')
    def test_manifest_duplicate_overlap_nonnull_or_bad_path_refuses(self):
        identity=sha256(b'{}').hexdigest();ref=[['x'],identity,2]
        examples=[{'data':{'x':None},'facts':[ref,ref]}, {'data':{'x':None},'facts':[ref,[['x','child'],identity,2]]}, {'data':{'x':False},'facts':[ref]}, {'data':[None],'facts':[[[True],identity,2]]}, {'data':[None],'facts':[[[-1],identity,2]]}, {'data':{},'facts':[[['missing'],identity,2]]}]
        for value in examples:
            with self.subTest(value=value),self.assertRaises(ValueError):f.descriptor(f.canonical(value))
    def test_bounds_original_depth_node_count_references_and_total_expansion(self):
        with self.assertRaises(ValueError):f.extract(b'['*65+b'0'+b']'*65)
        with self.assertRaises(ValueError):f.extract(b'['+b'0,'*f.MAX_NODES+b'0]')
        ref=[['x'],'a'*64,2]
        with self.assertRaises(ValueError):f.descriptor(f.canonical({'data':{'x':None},'facts':[ref]*(f.MAX_REFS+1)}))
        with self.assertRaises(ValueError):f.descriptor(f.canonical({'data':[None,None],'facts':[[[0],'a'*64,8*1024*1024],[[1],'b'*64,8*1024*1024]]}))
    def test_header_uses_expanded_original_size_and_exact_frame_delta(self):
        raw=f.canonical(self.example());base,_=f.extract(raw);new=self.example();new['source_at']='changed';target,facts=f.extract(f.canonical(new));operations=f.delta.make_delta(base,target)
        stored=f.encode_header(sha256(base).hexdigest(),f.canonical(new),len(target),operations);aid,size,digest,frame_size,ops=f.decode_header(stored)
        self.assertEqual(size,len(f.canonical(new)));restored=f.delta.apply_delta(base,ops,frame_size)
        self.assertEqual(f.expand(restored,facts,size,digest),f.canonical(new))
        for bad in (stored[:-3],stored.replace(str(size)+':','99999999:',1)):
            with self.assertRaises(ValueError):f.decode_header(bad)
    def test_public_expand_has_no_unchecked_descriptor_bypass(self):
        raw=f.canonical(self.example());descriptor,facts=f.extract(raw)
        with patch.object(f,'descriptor',side_effect=ValueError('validation sentinel')) as validation:
            with self.assertRaisesRegex(ValueError,'validation sentinel'):f.expand(descriptor,facts,len(raw),sha256(raw).hexdigest())
            validation.assert_called_once_with(descriptor)
        with self.assertRaises(TypeError):f.expand(descriptor,facts,len(raw),sha256(raw).hexdigest(),validated_descriptor=({},{}))
        bad_fact=b'{"exact": true}'
        identity=sha256(bad_fact).hexdigest();frame=f.canonical({'data':{'policy':None},'facts':[[['policy'],identity,len(bad_fact)]]})
        intended=f.canonical({'policy':{'exact':True}})
        with self.assertRaises(ValueError):f.expand(frame,{identity:bad_fact},len(f.canonical({'policy':None}))+len(bad_fact)-4,sha256(intended).hexdigest())

    def test_punctuation_heavy_inputs_avoid_unbounded_delta_index(self):
        self.assertFalse(f.delta_safe(b'['+b'0,'*300001+b'0]'))
        self.assertTrue(f.delta_safe(f.canonical(self.example())))

if __name__=='__main__':unittest.main()
