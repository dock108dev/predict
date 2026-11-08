"""Publication requires both immutable accounting and the live dispatch task."""
from copy import deepcopy
from unittest import TestCase
from app.storage.ordinary_publication import owned_refresh


class OwnedRefresh(TestCase):
    def test_exact_owned_progress_only(self):
        pending=dict(id='request',runtime_id='owner',candidate_digest='code',state='uncertain')
        progress=dict(id='request',runtime_id='owner',candidate_digest='code',stage='transport')
        q=dict(blocking_reason='ambiguous_dispatch_unresolved',pause=None,publication_pending=pending)
        owner=dict(healthy=True,active=True,runtime_id='owner',global_stopped=False,paused_sources=[],
            status=dict(sources=[dict(provider='the_odds_api',worker_done=False,publication_progress=progress)]))
        self.assertTrue(owned_refresh(owner,q))
        completed=deepcopy(owner);p=completed['status']['sources'][0]
        p['publication_progress']=None;p['publication_completions']=[dict(progress,stage='accounted',status=200,charged=3)]
        self.assertTrue(owned_refresh(completed,q))
        p['publication_completions'][0]['id']='other'
        self.assertFalse(owned_refresh(completed,q))
        for key,value in [('healthy',False),('active',False),('runtime_id','other'),('global_stopped',True),('paused_sources',['the_odds_api'])]:
            with self.subTest(owner=key):self.assertFalse(owned_refresh(dict(owner,**{key:value}),q))
        for key,value in [('pause','http_429'),('blocking_reason','quota_unknown'),('publication_pending',None)]:
            with self.subTest(quota=key):self.assertFalse(owned_refresh(owner,dict(q,**{key:value})))
        for key,value in [('id','other'),('candidate_digest','other'),('stage','failed'),('stage','cancelled')]:
            changed=deepcopy(owner);changed['status']['sources'][0]['publication_progress'][key]=value
            with self.subTest(progress=key,value=value):self.assertFalse(owned_refresh(changed,q))
        changed=deepcopy(owner);changed['status']['sources'][0]['worker_done']=True
        self.assertFalse(owned_refresh(changed,q))
