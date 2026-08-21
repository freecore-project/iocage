import json
from pathlib import Path

import pytest

import iocage_lib.ioc_json as ioc_json
import iocage_lib.ioc_plugin as ioc_plugin
import iocage_lib.iocage as iocage


def write_index(path):
    path.joinpath('INDEX').write_text(json.dumps({
        'transmission': {
            'name': 'Transmission',
            'description': 'BitTorrent client',
        },
    }))


@pytest.mark.parametrize('repository', [
    'https://github.com/freenas/iocage-ix-plugins.git',
    'https://github.com/truenas/iocage-ix-plugins.git',
    'https://github.com/ix-plugin-hub/iocage-plugin-index.git',
])
def test_existing_ix_plugin_repository_is_preserved(repository):
    conf = {
        'type': 'plugin',
        'plugin_name': 'transmission',
        'plugin_repository': repository,
    }

    changed = object.__new__(ioc_json.IOCJson).fix_properties(conf)

    assert changed is False
    assert conf['plugin_repository'] == repository


@pytest.mark.parametrize('repository', [
    'https://plugins.freecore.org/plugins/git/iocage-zfs-plugins.git',
    'https://plugins.freecore.org/plugins/iocage-zfs-plugins.git',
    'https://plugins.freecore.org/truenas/iocage-zfs-plugins.git',
])
def test_retired_freecore_repository_normalizes_to_current_catalog(repository):
    conf = {
        'type': 'plugin',
        'plugin_name': 'transmission',
        'plugin_repository': repository,
    }

    changed = object.__new__(ioc_json.IOCJson).fix_properties(conf)

    assert changed is True
    assert conf['plugin_repository'] == ioc_json.OFFICIAL_PLUGIN_REPOSITORY


def test_explicit_retired_freecore_repository_uses_current_catalog():
    assert ioc_json.normalize_plugin_repository(
        'https://plugins.freecore.org/plugins/git/iocage-zfs-plugins.git'
    ) == ioc_json.OFFICIAL_PLUGIN_REPOSITORY


def test_missing_plugin_repository_normalizes_to_current_catalog():
    conf = {
        'type': 'plugin',
        'plugin_name': 'transmission',
    }

    changed = object.__new__(ioc_json.IOCJson).fix_properties(conf)

    assert changed is True
    assert conf['plugin_repository'] == ioc_json.OFFICIAL_PLUGIN_REPOSITORY


def test_cli_defaults_to_current_freecore_catalog():
    source = (Path(__file__).parents[2] / 'iocage_cli' / 'fetch.py').read_text()

    assert 'default=ioc_json.OFFICIAL_PLUGIN_REPOSITORY' in source


@pytest.mark.parametrize('repository', [
    'https://github.com/freenas/iocage-ix-plugins.git',
    'https://github.com/truenas/iocage-ix-plugins',
    'git@github.com:ix-plugin-hub/iocage-plugin-index.git',
])
def test_new_plugin_creation_rejects_legacy_ix_catalog(repository):
    plugin = object.__new__(ioc_plugin.IOCPlugin)
    plugin.git_repository = repository
    plugin.callback = None
    plugin.silent = True

    with pytest.raises(RuntimeError, match='cannot be created'):
        plugin.fetch_plugin((), 0, False)


def test_plugin_index_rejects_legacy_catalog_before_clone():
    plugin = object.__new__(ioc_plugin.IOCPlugin)
    plugin.git_repository = (
        'https://github.com/truenas/iocage-ix-plugins.git'
    )
    plugin.callback = None
    plugin.silent = True
    plugin.pull_clone_git_repo = lambda: pytest.fail('legacy catalog cloned')

    with pytest.raises(RuntimeError, match='cannot be created'):
        plugin.fetch_plugin_index(())


def test_iocage_create_rejects_legacy_catalog_before_discovery():
    instance = object.__new__(iocage.IOCage)
    instance.callback = None
    instance.silent = True

    with pytest.raises(RuntimeError, match='cannot be created'):
        instance.fetch(
            plugins=True,
            plugin_name='transmission',
            git_repository=(
                'https://github.com/truenas/iocage-ix-plugins.git'
            ),
        )


def test_current_freecore_plugin_repository_allows_creation_path():
    class CreationPathReached(Exception):
        pass

    def creation_path(*args, **kwargs):
        raise CreationPathReached

    plugin = object.__new__(ioc_plugin.IOCPlugin)
    plugin.git_repository = ioc_json.OFFICIAL_PLUGIN_REPOSITORY
    plugin.fetch_plugin_index = creation_path
    plugin.callback = None
    plugin.silent = True

    with pytest.raises(CreationPathReached):
        plugin.fetch_plugin((), 0, False)


def test_fetch_plugin_index_preserves_requested_jail_name(tmp_path):
    write_index(tmp_path)
    plugin = object.__new__(ioc_plugin.IOCPlugin)
    plugin.git_repository = ioc_json.OFFICIAL_PLUGIN_REPOSITORY
    plugin.git_destination = str(tmp_path)
    plugin.plugin = 'transmission'
    plugin.jail = 'custom-transmission'
    plugin.callback = None
    plugin.silent = True
    plugin.pull_clone_git_repo = lambda: None
    fetched = {}
    plugin.fetch_plugin = lambda props, num, accept: fetched.update({
        'props': props,
        'num': num,
        'accept': accept,
        'jail': plugin.jail,
    })

    plugin.fetch_plugin_index(('vnet=1',), accept_license=True)

    assert plugin.plugin == 'transmission'
    assert fetched == {
        'props': ('vnet=1',),
        'num': 0,
        'accept': True,
        'jail': 'custom-transmission',
    }


def test_fetch_plugin_index_generates_default_jail_name(tmp_path, monkeypatch):
    write_index(tmp_path)
    monkeypatch.setattr(ioc_plugin.uuid, 'uuid4', lambda: 'abcd1234')
    plugin = object.__new__(ioc_plugin.IOCPlugin)
    plugin.git_repository = ioc_json.OFFICIAL_PLUGIN_REPOSITORY
    plugin.git_destination = str(tmp_path)
    plugin.plugin = 'transmission'
    plugin.jail = None
    plugin.callback = None
    plugin.silent = True
    plugin.pull_clone_git_repo = lambda: None
    fetched = {}
    plugin.fetch_plugin = lambda props, num, accept: fetched.update({
        'jail': plugin.jail,
    })

    plugin.fetch_plugin_index(())

    assert fetched['jail'] == 'transmission_abcd'


def test_fetch_plugins_path_passes_name_and_keep_jail_on_failure(monkeypatch):
    captured = {}

    class FakePlugin:
        def __init__(self, **kwargs):
            captured['init'] = kwargs

        def fetch_plugin_index(self, props, **kwargs):
            captured['props'] = props
            captured['fetch'] = kwargs

    monkeypatch.setattr(
        iocage.ioc_common, 'checkoutput', lambda cmd: '15.0-RELEASE')
    monkeypatch.setattr(iocage.ioc_plugin, 'IOCPlugin', FakePlugin)
    instance = object.__new__(iocage.IOCage)
    instance.silent = True
    instance.callback = None
    instance.jails = {}

    instance.fetch(
        release='15.0-RELEASE',
        name='custom-transmission',
        props=('vnet=1',),
        plugins=True,
        plugin_name='transmission',
        accept=True,
        keep_jail_on_failure=True,
    )

    assert captured['init']['jail'] == 'custom-transmission'
    assert captured['init']['keep_jail_on_failure'] is True
    assert captured['init']['plugin'] == 'transmission'
    assert captured['props'] == ('vnet=1',)
    assert captured['fetch']['accept_license'] is True
