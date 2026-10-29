"""Tests never inherit the workstation owner's paid acquisition authority."""
import pytest


@pytest.fixture(autouse=True)
def isolated_acquisition_authority(tmp_path, monkeypatch):
    # Scenarios exercising explicit grants install their own authored file.
    monkeypatch.setattr('app.collection.alternate_acquisition.AUTHORITY_PATH',
                        tmp_path / 'alternate-authority.json')
