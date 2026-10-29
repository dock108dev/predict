"""Quiet books retain continuity; outstanding work and recovery remain visible."""
from datetime import datetime, timezone, timedelta
from app.collection.native_synchronization import Synchronization


def ready():
    owner=Synchronization();owner.begin(1,['a','b']);owner.acknowledge(17,3)
    owner.image('a');owner.image('b');owner.persist(1,['a','b'])
    return owner,dict(stream_connected=True)


def test_quiet_books_do_not_require_recent_price_changes_or_repeated_snapshots():
    owner,metrics=ready()
    owner.delivered('raw',[(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()])
    result=owner.snapshot(metrics)
    assert result['state']=='synchronized'
    assert result['initial_images']==2
    assert result['price_change_age_is_sync_age'] is False
    assert owner.snapshot(metrics,enabled=False)['state']=='disconnected'


def test_each_pipeline_stage_prevents_false_caught_up_state():
    owner,metrics=ready()
    for key in ('receive_buffer_frames','reconstruction_inflight_frames','reconstruction_ready_frames',
                'processing_inflight_frames','raw_backlog','raw_inflight_images'):
        assert owner.snapshot(dict(metrics,raw_oldest_pending_seconds=3,**{key:1}))['state']=='catching_up',key
    # Expensive derived work is measured independently from raw synchronization.
    result=owner.snapshot(dict(metrics,derived_inflight_images=5,pending_books=7))
    assert result['state']=='synchronized' and result['derived_pending_images']==12
    assert owner.snapshot(dict(metrics,stream_connected=False))['state']=='disconnected'


def test_gaps_reconnect_missing_images_and_isolation_never_inherit_authority():
    owner,metrics=ready();owner.revoke('sequence_gap')
    assert owner.snapshot(metrics)['continuity_intact'] is False
    owner.begin(2,['a','b','c'])
    assert owner.snapshot(metrics)['state']=='awaiting_subscription'
    owner.acknowledge(18,1);owner.image('a')
    assert owner.snapshot(metrics)['state']=='initializing'
    assert owner.snapshot(metrics)['missing_images']==2
    owner.invalidate('b')
    assert owner.snapshot(metrics)['state']=='partial'
    owner.image('b');owner.image('c')
    assert owner.snapshot(metrics)['state']=='initializing'
    owner.persist(1,['a','b','c'])  # Old-generation SQL completion cannot restore authority.
    assert owner.snapshot(metrics)['missing_durable_images']==3
    owner.persist(2,['a','b','c'])
    assert owner.snapshot(metrics)['state']=='synchronized'
    owner.revoke('catalog_changed')
    assert owner.snapshot(metrics)['state']=='disconnected'


def test_latency_samples_are_bounded_and_separate_by_delivery_stage():
    owner,_=ready();now=datetime.now(timezone.utc).isoformat()
    owner.delivered('raw',[now]*3000)
    result=owner.snapshot(dict(stream_connected=True))
    assert result['delivery_latency']['raw']['samples']==2048
    assert result['delivery_latency']['derived']['samples']==0


def test_active_low_latency_stream_does_not_require_an_empty_simultaneous_sample():
    owner,metrics=ready()
    result=owner.snapshot(dict(metrics,raw_backlog=1,raw_oldest_pending_seconds=.1))
    assert result['state']=='streaming' and result['current']
    assert result['raw_pending_images']==1
    result=owner.snapshot(dict(metrics,raw_backlog=1,raw_oldest_pending_seconds=3))
    assert result['state']=='catching_up' and not result['current']
