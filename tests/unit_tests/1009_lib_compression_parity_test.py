import subprocess as su
from unittest.mock import Mock, patch

import pytest

from iocage_lib.ioc_check import IOCCheck
from iocage_lib.ioc_fetch import IOCFetch
from iocage_lib.ioc_json import IOCJson
from iocage_lib.ioc_start import _create_jail_zfs_dataset


MANAGED_DATASETS = (
    'iocage',
    'iocage/download',
    'iocage/images',
    'iocage/jails',
    'iocage/log',
    'iocage/releases',
    'iocage/templates',
)


def ioc_check():
    check = IOCCheck.__new__(IOCCheck)
    check.pool = 'tank'
    check.reset_cache = False
    check.callback = None
    check.silent = True
    return check


def test_new_iocage_hierarchy_sets_lz4():
    created = []

    class MissingDataset:
        def __init__(self, name, cache=False):
            self.name = name
            self.exists = False
            self.path = f'/mnt/{name}'
            self.properties = {'exec': 'on'}

        def create(self, options):
            created.append((self.name, options))

    with patch('iocage_lib.ioc_check.Dataset', MissingDataset), patch(
        'iocage_lib.ioc_check.os.geteuid', return_value=0
    ), patch('iocage_lib.ioc_check.iocage_lib.ioc_common.logit'):
        ioc_check().__check_datasets__()

    assert created == [
        (
            f'tank/{dataset}',
            {
                'properties': {
                    'compression': 'lz4',
                    'aclmode': 'passthrough',
                    'aclinherit': 'passthrough',
                },
            },
        )
        for dataset in MANAGED_DATASETS
    ]


def test_existing_iocage_hierarchy_is_not_rewritten():
    class ExistingDataset:
        def __init__(self, name, cache=False):
            self.name = name
            self.exists = True
            self.path = f'/mnt/{name}'
            self.properties = {'exec': 'on', 'compression': 'zstd'}

        def create(self, options):
            raise AssertionError('existing datasets must not be recreated')

        def set_property(self, prop, value):
            raise AssertionError('existing compression must not be rewritten')

    with patch('iocage_lib.ioc_check.Dataset', ExistingDataset), patch(
        'iocage_lib.ioc_check.iocage_lib.ioc_common.logit'
    ):
        ioc_check().__check_datasets__()


def fetcher():
    fetch = IOCFetch.__new__(IOCFetch)
    fetch.pool = 'tank'
    fetch.iocroot = '/mnt/tank/iocage'
    fetch.release = '15.0-RELEASE'
    fetch.zpool = Mock()
    return fetch


def test_release_download_dataset_sets_lz4():
    fetch = fetcher()
    dataset = Mock(exists=False, mounted=True)

    with patch('iocage_lib.ioc_fetch.os.path.isdir', return_value=False), patch(
        'iocage_lib.ioc_fetch.Dataset', return_value=dataset
    ):
        fetch.fetch_download([])

    dataset.create.assert_called_once_with({
        'properties': {'compression': 'lz4'},
    })


def test_local_release_dataset_sets_lz4(tmp_path):
    fetch = fetcher()
    fetch.http = False
    fetch._file = True
    fetch.root_dir = str(tmp_path)
    fetch.files = []

    with patch('iocage_lib.ioc_fetch.os.path.isdir', return_value=False):
        fetch.fetch_release()

    fetch.zpool.create_dataset.assert_called_once_with({
        'name': 'tank/iocage/download/15.0-RELEASE',
        'properties': {'compression': 'lz4'},
    })


def test_extracted_release_root_sets_lz4():
    fetch = fetcher()
    archive = Mock()
    archive_context = Mock()
    archive_context.__enter__ = Mock(return_value=archive)
    archive_context.__exit__ = Mock(return_value=False)

    with patch('iocage_lib.ioc_fetch.os.path.isdir', return_value=False), patch(
        'iocage_lib.ioc_fetch.tarfile.open', return_value=archive_context
    ), patch.object(
        fetch, '__fetch_extract_remove__', return_value=[]
    ), patch.object(
        fetch, '__fetch_check_members__', return_value=[]
    ):
        fetch.fetch_extract('base.txz')

    fetch.zpool.create_dataset.assert_called_once_with({
        'name': 'tank/iocage/releases/15.0-RELEASE/root',
        'create_ancestors': True,
        'properties': {'compression': 'lz4'},
    })


@pytest.mark.parametrize(
    'template, dataset_type',
    [(0, 'jails'), (1, 'templates')],
)
def test_compression_property_updates_real_zfs_dataset(
    template, dataset_type
):
    iocjson = IOCJson.__new__(IOCJson)
    iocjson.pool = 'tank'
    iocjson.callback = None
    iocjson.silent = True
    dataset = Mock()
    conf = {
        'host_hostuuid': 'example',
        'template': template,
        'compression': 'zstd',
    }

    with patch('iocage_lib.ioc_json.Dataset', return_value=dataset) as cls:
        value, returned_conf = iocjson.json_check_prop(
            'compression', 'zstd', conf
        )

    cls.assert_called_once_with(f'tank/iocage/{dataset_type}/example')
    dataset.set_property.assert_called_once_with('compression', 'zstd')
    assert value == 'zstd'
    assert returned_conf is conf


def test_setting_compression_keeps_json_and_zfs_in_sync():
    iocjson = IOCJson.__new__(IOCJson)
    iocjson.pool = 'tank'
    iocjson.location = '/mnt/tank/iocage/jails/example'
    iocjson.callback = None
    iocjson.silent = True
    conf = {
        'host_hostuuid': 'example',
        'template': 0,
    }
    dataset = Mock()
    process = Mock()
    process.communicate.return_value = (b'', b'')
    jail_list = Mock()
    jail_list.list_get_jid.return_value = (False, None)

    with patch.object(
        iocjson, 'json_load', return_value=(conf, False)
    ), patch.object(
        iocjson, 'get_full_config', return_value={'compression': 'lz4'}
    ), patch.object(
        iocjson, 'json_write'
    ) as json_write, patch(
        'iocage_lib.ioc_json.iocage_lib.ioc_list.IOCList',
        return_value=jail_list,
    ), patch(
        'iocage_lib.ioc_json.su.Popen', return_value=process
    ), patch(
        'iocage_lib.ioc_json.Dataset', return_value=dataset
    ), patch('iocage_lib.ioc_json.iocage_lib.ioc_common.logit'):
        iocjson.json_set_value('compression=zstd')

    dataset.set_property.assert_called_once_with('compression', 'zstd')
    json_write.assert_called_once_with(conf)
    assert conf['compression'] == 'zstd'


def test_delegated_jail_dataset_sets_lz4_and_mountpoint():
    with patch(
        'iocage_lib.ioc_start.iocage_lib.ioc_common.checkoutput'
    ) as checkoutput:
        _create_jail_zfs_dataset('tank', 'iocage/jails/example/data')

    checkoutput.assert_called_once_with(
        [
            'zfs', 'create', '-o', 'compression=lz4', '-o',
            'mountpoint=none', 'tank/iocage/jails/example/data',
        ],
        stderr=su.STDOUT,
    )
