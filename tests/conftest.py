"""Tests never inherit the workstation owner's paid acquisition authority."""
import pytest


@pytest.fixture(autouse=True)
def isolated_acquisition_authority(tmp_path, monkeypatch):
    # Scenarios exercising explicit grants install their own authored file.
    monkeypatch.setattr('app.collection.alternate_acquisition.AUTHORITY_PATH',
                        tmp_path / 'alternate-authority.json')
    # Background personal tracking must never write fixture observations into
    # the workstation owner's durable My Bets journal.
    monkeypatch.setenv('PREDICT_BET_JOURNAL_PATH', str(tmp_path / 'personal-bets.sqlite3'))
