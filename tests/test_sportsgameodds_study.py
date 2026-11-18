from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.collection.sportsgameodds_study import observe, report

NOW = datetime(2026, 11, 18, 20, tzinfo=timezone.utc)


def page(at, price='-110', source=None, *, starts=None, phase='pregame'):
    event = dict(event_id='game', starts_at=(starts or NOW+timedelta(minutes=20)).isoformat(),
                 received_at=at.isoformat(), phase=phase)
    quote = dict(event_id='game',venue='novig',odd_id='home',line='-1.5',
                 price_american=price,available=True,provider_available=True,
                 alternate=False,source_at=(source or NOW).isoformat())
    return SimpleNamespace(events=(event,),quotes=(quote,))


def test_measurement_is_durable_and_distinguishes_price_clock_and_repeated_images(tmp_path):
    path=tmp_path/'study.sqlite3'
    assert report(path)['samples'] == 0
    patterns=[('-110',0),('-110',0),('-105',2),('-105',3),('-105',3),('-110',5)]
    for minute,(price,clock) in enumerate(patterns):
        at=NOW+timedelta(minutes=minute)
        result=observe(path,page(at,price,NOW+timedelta(minutes=clock)),at)
    assert result == report(path)
    assert result['samples'] == 6 and result['comparable_polls'] == 5
    assert result['quote_image_changes'] == 2
    assert result['source_clock_image_changes'] == 3
    assert result['clock_only_changes'] == 1
    assert result['fully_repeated_polls'] == 2
    assert result['earlier_changed_images_vs_3m'] == 2
    assert result['poll_gap_seconds'] == dict(min=60,max=60,mean=60)
    assert path.stat().st_mode & 0o777 == 0o600
    # Duplicate receipts never manufacture additional samples.
    assert observe(path,page(at,price,NOW+timedelta(minutes=clock)),at)['samples'] == 6


def test_study_excludes_early_live_and_post_kickoff_pages(tmp_path):
    path=tmp_path/'study.sqlite3'
    for starts,phase in ((NOW+timedelta(hours=1),'pregame'),(NOW,'pregame'),
                         (NOW+timedelta(minutes=1),'live')):
        assert observe(path,page(NOW,starts=starts,phase=phase),NOW)['samples'] == 0
    assert not path.exists()


def test_sample_capacity_and_quote_order_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr('app.collection.sportsgameodds_study.MAX_SAMPLES',3)
    path=tmp_path/'study.sqlite3'
    for minute in range(5):
        at=NOW+timedelta(minutes=minute)
        packet=page(at)
        quote=dict(packet.quotes[0],venue='fanduel')
        packet.quotes=(quote,*packet.quotes) if minute%2 else (*packet.quotes,quote)
        result=observe(path,packet,at)
    assert result['samples'] == 3
    assert result['quote_image_changes'] == 0
    assert result['fully_repeated_polls'] == 2
