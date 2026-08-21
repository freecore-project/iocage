import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import iocage_lib.ioc_exceptions as ioc_exceptions
import iocage_lib.ioc_json as ioc_json
import iocage_lib.ioc_list as ioc_list
import iocage_lib.ioc_plugin as ioc_plugin
import iocage_lib.iocage as iocage


def _load_cli_module(name):
    path = Path(__file__).parents[2] / 'iocage_cli' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(
        f'iocage_test_{name}_cli', path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch_cli = _load_cli_module('fetch')
list_cli = _load_cli_module('list')


LEGACY_PLUGIN_CONFIG = {
    'CONFIG_VERSION': '34',
    'CONFIG_TYPE': 'THICK',
    'host_hostuuid': 'legacy_plugin',
    'type': 'pluginv2',
    'release': '13.3-RELEASE',
    'plugin_name': 'legacy-plugin',
    'plugin_repository': 'git://legacy.example/plugin-index.git',
    'ip4_addr': 'none',
    'ip6_addr': 'none',
    'dhcp': 0,
    'boot': 0,
    'basejail': 0,
    'template': 0,
    'depends': 'none',
}


def _iocage_without_init(iocroot='', jail='legacy_plugin'):
    instance = iocage.IOCage.__new__(iocage.IOCage)
    instance.iocroot = str(iocroot)
    instance.jail = jail
    instance.jails = {}
    instance.callback = None
    instance.silent = False
    instance.rc = False
    instance._all = False
    instance.skip_jails = False
    instance.is_depend = False
    return instance


@pytest.mark.parametrize(
    'kwargs',
    [
        {'plugins': True, 'list': True},
        {'plugins': True},
        {'plugin_name': 'legacy-plugin'},
    ],
)
def test_iocage_fetch_rejects_plugin_paths_before_host_or_network(kwargs):
    instance = _iocage_without_init()
    with mock.patch.object(
        iocage.ioc_common, 'checkoutput',
        side_effect=AssertionError('host command must not run'),
    ), mock.patch.object(
        iocage.ioc_plugin, 'IOCPlugin',
        side_effect=AssertionError('plugin client must not be constructed'),
    ):
        with pytest.raises(ioc_exceptions.PluginOperationRetired):
            instance.fetch(**kwargs)


def test_cli_plugin_fetch_rejects_before_proxy_environment_change():
    old_http_proxy = os.environ.get('http_proxy')
    old_https_proxy = os.environ.get('https_proxy')

    with pytest.raises(ioc_exceptions.PluginOperationRetired):
        fetch_cli.cli.callback(
            plugins=True,
            plugin_name=None,
            proxy='http://proxy.invalid',
        )

    assert os.environ.get('http_proxy') == old_http_proxy
    assert os.environ.get('https_proxy') == old_https_proxy


def test_cli_remote_plugin_list_rejects_before_host_discovery():
    with mock.patch.object(
        list_cli.ioc_common, 'checkoutput',
        side_effect=AssertionError('host command must not run'),
    ):
        with pytest.raises(ioc_exceptions.PluginOperationRetired):
            list_cli.cli.callback(
                dataset_type=None,
                header=False,
                _long=False,
                remote=True,
                http=True,
                plugins=True,
                _sort='name',
                quick=False,
                official=False,
            )


@pytest.mark.parametrize(
    ('method_name', 'args'),
    [
        ('pull_clone_git_repo', ()),
        ('fetch_plugin_packagesites', (['https://pkg.invalid'],)),
        ('fetch_plugin_versions_from_plugin_index', ({},)),
        ('fetch_plugin_versions', ()),
        ('retrieve_plugin_json', ()),
        ('fetch_plugin', ((), 0, False)),
        ('fetch_plugin_index', ((),)),
        ('update', ('42',)),
        ('upgrade', ('42',)),
    ],
)
def test_direct_remote_plugin_entrypoints_are_retired(method_name, args):
    plugin = ioc_plugin.IOCPlugin.__new__(ioc_plugin.IOCPlugin)
    plugin.callback = None
    plugin.silent = False

    with mock.patch.object(
        ioc_plugin.requests, 'get',
        side_effect=AssertionError('HTTP must not run'),
    ) as requests_get:
        with pytest.raises(ioc_exceptions.PluginOperationRetired):
            getattr(plugin, method_name)(*args)

    requests_get.assert_not_called()


def test_low_level_plugin_git_entrypoint_is_retired_before_import_or_io(
    tmp_path,
):
    destination = tmp_path / 'plugin-index'

    with pytest.raises(ioc_exceptions.PluginOperationRetired):
        ioc_plugin.IOCPlugin._clone_repo(
            'main', 'https://git.invalid/plugins.git', str(destination)
        )

    assert not destination.exists()


@pytest.mark.parametrize('operation', ['update', 'upgrade'])
def test_plugin_update_and_upgrade_reject_before_config_migration_or_io(
    tmp_path, operation,
):
    jail_path = tmp_path / 'jails' / 'legacy_plugin'
    jail_path.mkdir(parents=True)
    config_path = jail_path / 'config.json'
    config_path.write_text(json.dumps(LEGACY_PLUGIN_CONFIG, indent=2) + '\n')
    original = config_path.read_bytes()
    instance = _iocage_without_init(tmp_path)

    with mock.patch.object(
        iocage.ioc_json, 'IOCJson',
        side_effect=AssertionError('configuration migration must not run'),
    ), mock.patch.object(
        iocage.ioc_common, 'check_release_newer',
        side_effect=AssertionError('release discovery must not run'),
    ), mock.patch.object(
        iocage.ioc_common, 'checkoutput',
        side_effect=AssertionError('host command must not run'),
    ), mock.patch.object(
        iocage.ioc_plugin, 'IOCPlugin',
        side_effect=AssertionError('plugin client must not be constructed'),
    ):
        with pytest.raises(ioc_exceptions.PluginOperationRetired):
            if operation == 'update':
                instance.update()
            else:
                instance.upgrade('15.0-RELEASE')

    assert config_path.read_bytes() == original


def test_plugin_property_fix_preserves_legacy_identity_exactly():
    configuration = ioc_json.IOCJson.__new__(ioc_json.IOCJson)
    configuration.iocroot = '/unused'
    conf = {
        'type': 'pluginv2',
        'host_hostuuid': 'legacy_plugin',
        'plugin_name': 'legacy-plugin',
        'plugin_repository': 'git://legacy.example/plugin-index.git',
    }
    expected = conf.copy()

    assert configuration.fix_properties(conf) is False
    assert conf == expected


def test_local_plugin_list_uses_only_stored_config_and_manifest(tmp_path):
    jail_path = tmp_path / 'legacy_plugin'
    jail_path.mkdir()
    config_path = jail_path / 'config.json'
    manifest_path = jail_path / 'legacy-plugin.json'
    config_path.write_text(json.dumps(LEGACY_PLUGIN_CONFIG, indent=2) + '\n')
    manifest = {
        'name': 'Legacy Plugin',
        'primary_pkg': 'legacy-pkg',
        'category': 'legacy-category',
        'maintainer': 'legacy@example.invalid',
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    original_config = config_path.read_bytes()
    original_manifest = manifest_path.read_bytes()

    listing = ioc_list.IOCList.__new__(ioc_list.IOCList)
    listing.full = True
    listing.plugin = True
    listing.plugin_data = True
    listing.basejail_only = False
    listing.header = False
    listing.sort = 'name'
    listing.callback = None
    listing.silent = False

    jail = SimpleNamespace(
        name='pool/iocage/jails/legacy_plugin',
        properties={'mountpoint': str(jail_path)},
    )
    config_reader = mock.Mock()
    config_reader.json_get_value.return_value = LEGACY_PLUGIN_CONFIG.copy()
    root_dataset = SimpleNamespace(exists=False)

    with mock.patch.object(
        ioc_list.iocage_lib.ioc_common, 'get_active_jails', return_value={},
    ), mock.patch.object(
        ioc_list.iocage_lib.ioc_common, 'get_host_gateways', return_value={},
    ), mock.patch.object(
        ioc_list.iocage_lib.ioc_common, 'retrieve_ip4_for_jail',
        return_value={'full_ip4': None, 'short_ip4': None},
    ), mock.patch.object(
        ioc_list.iocage_lib.ioc_json, 'IOCJson',
        return_value=config_reader,
    ), mock.patch.object(
        ioc_list, 'Dataset', return_value=root_dataset,
    ), mock.patch.object(
        ioc_plugin, 'IOCPlugin',
        side_effect=AssertionError('plugin client must not be constructed'),
    ):
        rows = listing.list_all([jail])

    assert rows[0][-5:] == [
        'legacy-plugin',
        'git://legacy.example/plugin-index.git',
        'legacy-pkg',
        'legacy-category',
        'legacy@example.invalid',
    ]
    assert config_path.read_bytes() == original_config
    assert manifest_path.read_bytes() == original_manifest


def test_existing_plugin_local_lifecycle_preserves_metadata(tmp_path):
    jail_path = tmp_path / 'legacy_plugin'
    jail_path.mkdir()
    config_path = jail_path / 'config.json'
    manifest_path = jail_path / 'legacy-plugin.json'
    config_path.write_text(json.dumps(LEGACY_PLUGIN_CONFIG, indent=2) + '\n')
    manifest_path.write_text('{"name":"Legacy Plugin"}\n')
    original_config = config_path.read_bytes()
    original_manifest = manifest_path.read_bytes()
    instance = _iocage_without_init(tmp_path.parent)
    instance.__check_jail_existence__ = mock.Mock(
        return_value=('legacy_plugin', str(jail_path))
    )
    instance.list = mock.Mock(return_value=(False, None))
    config_reader = mock.Mock()
    config_reader.json_get_value.return_value = LEGACY_PLUGIN_CONFIG.copy()

    with mock.patch.object(
        iocage.ioc_json, 'IOCJson', return_value=config_reader,
    ), mock.patch.object(
        iocage.ioc_common, 'check_release_newer', return_value=False,
    ), mock.patch.object(iocage.ioc_start, 'IOCStart') as start, \
            mock.patch.object(iocage.ioc_stop, 'IOCStop') as stop, \
            mock.patch.object(iocage.ioc_image, 'IOCImage') as image:
        instance.start()
        instance.stop()
        instance.restart()
        instance.export()

    assert start.call_count == 2
    assert stop.call_count == 2
    image.return_value.export_jail.assert_called_once_with(
        'legacy_plugin', str(jail_path), compression_algo='zip'
    )
    assert config_path.read_bytes() == original_config
    assert manifest_path.read_bytes() == original_manifest


def test_ordinary_release_fetch_remains_available():
    instance = _iocage_without_init()
    fetcher = mock.Mock()

    with mock.patch.object(
        iocage.ioc_common, 'checkoutput', return_value='15.0-RELEASE',
    ), mock.patch.object(
        iocage.os, 'uname', return_value=('', '', '', '', 'amd64'),
    ), mock.patch.object(iocage.ioc_fetch, 'IOCFetch', return_value=fetcher):
        instance.fetch(
            release='15.0-RELEASE',
            files=['MANIFEST'],
            server='download.freebsd.org',
        )

    fetcher.fetch_release.assert_called_once_with()
