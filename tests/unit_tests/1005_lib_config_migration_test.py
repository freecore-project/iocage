from unittest.mock import patch

import pytest

from iocage_lib.ioc_json import IOCConfiguration


def configuration():
    config = IOCConfiguration.__new__(IOCConfiguration)
    config.json_version = IOCConfiguration.get_version()
    config.callback = None
    config.silent = True
    return config


def migrate(conf, default=True):
    config = configuration()
    with patch('iocage_lib.ioc_json.os.geteuid', return_value=0):
        if default:
            return config.check_config(conf, default=True)
        with patch.object(config, 'check_jail_config', return_value=conf):
            return config.check_config(conf)


@patch.object(IOCConfiguration, 'get_mac_prefix', return_value='aabbcc')
def test_freecore_defaults_preserve_truenas_networking_and_storage(_):
    defaults = IOCConfiguration.retrieve_default_props()

    assert defaults['CONFIG_VERSION'] == '34'
    assert defaults['vnet_default_interface'] == 'auto'
    assert defaults['compression'] == 'lz4'
    assert defaults['host_domainname'] == 'none'
    assert defaults['allow_mount_fdescfs'] == 0
    assert defaults['allow_mount_linprocfs'] == 0
    assert defaults['allow_mount_linsysfs'] == 0
    assert defaults['allow_nfsd'] == 0


@pytest.mark.parametrize(
    'value, expected',
    [
        (None, 'auto'),
        ('auto', 'auto'),
        ('none', 'none'),
        ('igb0', 'igb0'),
    ],
)
def test_config_28_migration_preserves_explicit_network_selection(
    value, expected
):
    conf = {
        'CONFIG_VERSION': '28',
        'host_domainname': 'none',
        'compression': 'lz4',
    }
    if value is not None:
        conf['vnet_default_interface'] = value

    migrated, write = migrate(conf)

    assert write is True
    assert migrated['CONFIG_VERSION'] == '34'
    assert migrated['vnet_default_interface'] == expected


def test_config_28_migration_adds_only_missing_freecore_defaults():
    conf = {
        'CONFIG_VERSION': '28',
        'future_vendor_property': 'preserve-me',
    }

    migrated, write = migrate(conf)

    assert write is True
    assert migrated['vnet_default_interface'] == 'auto'
    assert migrated['compression'] == 'lz4'
    assert migrated['host_domainname'] == 'none'
    assert migrated['allow_mount_fdescfs'] == 0
    assert migrated['allow_mount_linprocfs'] == 0
    assert migrated['allow_mount_linsysfs'] == 0
    assert migrated['allow_nfsd'] == 0
    assert migrated['future_vendor_property'] == 'preserve-me'


@pytest.mark.parametrize('version', ('28', '29', '30', '31', '32', '33'))
def test_config_versions_28_to_33_migrate_to_schema_34(version):
    migrated, write = migrate({'CONFIG_VERSION': version})

    assert write is True
    assert migrated['CONFIG_VERSION'] == '34'
    assert migrated['vnet_default_interface'] == 'auto'
    assert migrated['compression'] == 'lz4'
    assert migrated['host_domainname'] == 'none'


@pytest.mark.parametrize(
    'domainname, compression',
    [
        ('', 'on'),
        ('example.test', 'gzip-9'),
        ('none', 'lz4'),
    ],
)
def test_config_28_migration_does_not_rewrite_explicit_product_values(
    domainname, compression
):
    conf = {
        'CONFIG_VERSION': '28',
        'host_domainname': domainname,
        'compression': compression,
        'vnet_default_interface': 'auto',
    }

    migrated, _ = migrate(conf)

    assert migrated['host_domainname'] == domainname
    assert migrated['compression'] == compression


def test_migration_is_idempotent():
    migrated, first_write = migrate({'CONFIG_VERSION': '28'})
    snapshot = migrated.copy()

    migrated_again, second_write = migrate(migrated)

    assert first_write is True
    assert second_write is False
    assert migrated_again == snapshot


def test_versionless_thin_config_is_not_rewritten():
    conf = {'CONFIG_TYPE': 'THIN', 'vnet_default_interface': 'none'}

    migrated, write = migrate(conf)

    assert write is False
    assert migrated == conf


def test_versionless_thick_config_is_migrated():
    conf = {
        'CONFIG_TYPE': 'THICK',
        'vnet_default_interface': 'none',
        'future_vendor_property': 'preserve-me',
    }

    migrated, write = migrate(conf, default=False)

    assert write is True
    assert migrated['CONFIG_VERSION'] == '34'
    assert migrated['vnet_default_interface'] == 'none'
    assert migrated['future_vendor_property'] == 'preserve-me'


def test_config_backup_semantics_are_preserved(tmp_path):
    location = tmp_path / 'config.json'
    contents = '{"CONFIG_VERSION": "28"}\n'
    location.write_text(contents)

    configuration().backup_iocage_jail_conf(str(location))

    assert (tmp_path / 'config_backup.json').read_text() == contents
