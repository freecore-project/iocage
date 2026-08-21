"""the internal development record: plugin update entry points 15.0 calls."""
import pytest

import iocage_lib.iocage as iocage_mod

UUID_PATH = '/iocage/jails/x'


class _Json:
    conf = {}

    def __init__(self, *args, **kwargs):
        pass

    def json_get_value(self, key):
        return dict(self.conf)


def _logit(calls):
    def logit(content, **kwargs):
        if content['level'] == 'EXCEPTION':
            raise RuntimeError(content['message'])
        calls.append(('log', content['message']))
    return logit


def _patch(monkeypatch, name, value):
    monkeypatch.setattr(iocage_mod.IOCage, name, value, raising=False)


def _iocage(monkeypatch, conf, calls):
    ioc = iocage_mod.IOCage.__new__(iocage_mod.IOCage)
    ioc._all = False
    ioc.silent = True
    ioc.callback = None
    ioc.jail = conf['host_hostuuid']
    _Json.conf = conf
    monkeypatch.setattr(iocage_mod.ioc_json, 'IOCJson', _Json)
    monkeypatch.setattr(iocage_mod.ioc_common, 'logit', _logit(calls))
    monkeypatch.setattr(iocage_mod.ioc_common, 'checkoutput',
                        lambda cmd, **kw: '15.1-RELEASE-p4')
    _patch(monkeypatch, '__check_jail_existence__',
           lambda self: (conf['host_hostuuid'], UUID_PATH))
    _patch(monkeypatch, 'list', lambda self, *a, **kw: (True, 7))
    for name in ('snapshot', 'restart', 'stop', 'start'):
        _patch(monkeypatch, name,
               lambda self, *a, _n=name, **kw: calls.append((_n,)))

    class _Plugin:
        manifest_release = '15.1-RELEASE'

        def __init__(self, **kwargs):
            calls.append(('IOCPlugin', kwargs.get('plugin')))

        def update(self, jid):
            calls.append(('plugin.update', jid))

        def pull_clone_git_repo(self, depth=None):
            calls.append(('pull',))

        def _load_plugin_json(self):
            return {'release': self.manifest_release}

    class _Fetch:
        def __init__(self, release, server=None, verify=True,
                     callback=None):
            calls.append(('IOCFetch', release))

        def fetch_update(self, *params):
            calls.append(('fetch_update',) + tuple(params))

    monkeypatch.setattr(iocage_mod.ioc_plugin, 'IOCPlugin', _Plugin)
    monkeypatch.setattr(iocage_mod.ioc_fetch, 'IOCFetch', _Fetch)
    return ioc, _Plugin


PLUGIN = {
    'host_hostuuid': 'sync', 'type': 'pluginv2', 'basejail': 'yes',
    'release': '15.0-RELEASE-p14', 'plugin_name': 'syncthing',
    'plugin_repository': 'https://example.invalid/plugins.git',
}
JAIL = {
    'host_hostuuid': 'j1', 'type': 'jail', 'basejail': 'no',
    'release': '15.0-RELEASE-p14',
}


def _kinds(calls):
    return [c[0] for c in calls if c[0] != 'log']


@pytest.mark.parametrize('update_jail', [True, False])
def test_plugin_jail_patches_only_when_asked(monkeypatch, update_jail):
    calls = []
    ioc, _ = _iocage(monkeypatch, PLUGIN, calls)
    ioc.update(False, update_jail=update_jail)
    assert ('plugin.update', 7) in calls
    assert ('fetch_update' in _kinds(calls)) is update_jail


def test_an_ordinary_jail_is_always_patched(monkeypatch):
    calls = []
    ioc, _ = _iocage(monkeypatch, JAIL, calls)
    ioc.update(False, update_jail=False)
    assert ('fetch_update', True, 'j1') in calls
    assert 'plugin.update' not in _kinds(calls)


def test_the_113_keyword_call_still_patches(monkeypatch):
    calls = []
    ioc, _ = _iocage(monkeypatch, JAIL, calls)
    ioc.update(pkgs=False)  # the internal development record calls it this way
    assert 'fetch_update' in _kinds(calls)


def test_update_plugin_upgrades_across_majors(monkeypatch):
    calls = []
    ioc, plugin = _iocage(monkeypatch, PLUGIN, calls)
    plugin.manifest_release = '16.0-RELEASE'
    _patch(monkeypatch, 'upgrade',
           lambda self, release: calls.append(('upgrade', release)) or 'up')
    assert ioc.update_plugin(update_jail=False) == 'up'
    assert ('pull',) in calls and ('upgrade', None) in calls
    assert 'fetch_update' not in _kinds(calls)


@pytest.mark.parametrize('update_jail', [True, False])
def test_update_plugin_updates_within_a_major(monkeypatch, update_jail):
    calls = []
    ioc, plugin = _iocage(monkeypatch, PLUGIN, calls)
    seen = {}

    def update(self, pkgs=False, server=None, verify=True, *,
               update_jail=True):
        seen.update(pkgs=pkgs, update_jail=update_jail)

    _patch(monkeypatch, 'update', update)
    ioc.update_plugin(update_jail=update_jail)
    assert seen == {'pkgs': False, 'update_jail': update_jail}


def test_update_plugin_refuses_a_plain_jail(monkeypatch):
    calls = []
    ioc, _ = _iocage(monkeypatch, JAIL, calls)
    with pytest.raises(RuntimeError, match='is not a plugin'):
        ioc.update_plugin()
