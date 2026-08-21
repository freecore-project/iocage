from unittest.mock import Mock, call, patch

import pytest

import iocage_lib.zfs as zfs
from iocage_lib.cache import Cache
from iocage_lib.dataset import Dataset, Snapshot
from iocage_lib.ioc_destroy import IOCDestroy
from iocage_lib.ioc_exceptions import (
    JailMissingConfiguration,
    PoolNotActivated,
)
from iocage_lib.ioc_fstab import IOCFstab
from iocage_lib.ioc_image import IOCImage
from iocage_lib.pools import Pool


def _pool_properties(mounted='yes', encryption='off', keystatus='-'):
    return {
        'org.freebsd.ioc:active': 'yes',
        'mounted': mounted,
        'encryption': encryption,
        'keystatus': keystatus,
    }


def test_active_pool_cache_excludes_unmounted_and_locked_storage():
    storage_cache = Cache()
    storage_cache.pool_data = {
        'locked': {},
        'unmounted': {},
        'available': {},
    }
    storage_cache.dataset_data = {
        'locked': _pool_properties(
            encryption='aes-256-gcm', keystatus='unavailable'
        ),
        'unmounted': _pool_properties(mounted='no'),
        'available': _pool_properties(),
    }

    assert storage_cache.iocage_activated_pool_internal(False) == 'available'


@pytest.mark.parametrize(
    'properties',
    [
        _pool_properties(mounted='no'),
        _pool_properties(
            encryption='aes-256-gcm', keystatus='unavailable'
        ),
    ],
)
def test_active_pool_cache_never_selects_unavailable_storage(properties):
    storage_cache = Cache()
    storage_cache.pool_data = {'unavailable': {}}
    storage_cache.dataset_data = {'unavailable': properties}

    assert storage_cache.iocage_activated_pool_internal(False) is None


def test_dependent_cache_enumerates_only_requested_dataset_tree():
    storage_cache = Cache()
    dependents = [
        'tank/iocage/jails',
        'tank/iocage/jails/one',
        'tank/iocage/jails/one/root',
    ]

    with patch(
        'iocage_lib.cache.get_dependents', return_value=dependents
    ) as get_dependents:
        result = storage_cache.dependents_internal(
            'tank/iocage/jails', depth=None, lock=False
        )
        cached_result = storage_cache.dependents_internal(
            'tank/iocage/jails', depth=None, lock=False
        )

    assert result == dependents
    assert cached_result == dependents
    get_dependents.assert_called_once_with('tank/iocage/jails')
    assert storage_cache.dataset_dep_data == {
        'tank/iocage/jails': dependents
    }


@pytest.mark.parametrize(
    'properties, expected',
    [
        ({'mounted': 'yes', 'encryption': 'off'}, False),
        ({'mounted': 'no', 'encryption': 'off'}, True),
        ({
            'mounted': 'yes',
            'encryption': 'aes-256-gcm',
            'keystatus': 'unavailable',
        }, True),
        ({
            'mounted': 'yes',
            'encryption': 'aes-256-gcm',
            'keystatus': 'available',
        }, False),
    ],
)
def test_dataset_locked_includes_mount_and_key_availability(
    properties, expected
):
    dataset = Dataset('tank', cache=False)
    dataset._properties = properties

    assert dataset.locked is expected


def test_destroy_enumeration_can_include_unavailable_exact_target():
    parent = Dataset('tank/iocage/jails/broken', cache=False)

    class UnavailableDataset:
        name = 'tank/iocage/jails/broken'

        @property
        def locked(self):
            raise AssertionError('include_locked must not probe properties')

    unavailable = UnavailableDataset()
    with patch(
        'iocage_lib.dataset.get_dependents',
        return_value=[unavailable.name],
    ), patch('iocage_lib.dataset.Dataset', return_value=unavailable):
        result = list(parent.get_dependents(
            depth=None, ds_cache=False, include_locked=True
        ))

    assert result == [unavailable]


def test_snapshots_never_reuse_filesystem_property_cache():
    snapshot = Snapshot('tank/iocage/jails/one@snapshot', cache=True)

    assert snapshot.cache is False


@pytest.mark.parametrize('health', ['ONLINE', 'DEGRADED'])
def test_pool_activation_accepts_available_online_or_degraded_pool(health):
    pool = Pool('tank', cache=False)
    pool._properties = {'health': health}
    root_dataset = Mock(locked=False)

    with patch(
        'iocage_lib.pools.Dataset', return_value=root_dataset
    ), patch.object(pool, 'comment_check') as comment_check:
        pool.activate_pool()

    root_dataset.set_property.assert_called_once_with(
        'org.freebsd.ioc:active', 'yes'
    )
    comment_check.assert_called_once_with()


def test_pool_activation_rejects_unavailable_root_dataset():
    pool = Pool('tank', cache=False)
    pool._properties = {'health': 'ONLINE'}
    root_dataset = Mock(locked=True)

    with patch('iocage_lib.pools.Dataset', return_value=root_dataset):
        with pytest.raises(PoolNotActivated, match='mounted and unlocked'):
            pool.activate_pool()

    root_dataset.set_property.assert_not_called()


def test_pool_activation_rejects_faulted_pool_before_dataset_access():
    pool = Pool('tank', cache=False)
    pool._properties = {'health': 'FAULTED'}

    with patch('iocage_lib.pools.Dataset') as dataset:
        with pytest.raises(PoolNotActivated, match='ONLINE or DEGRADED'):
            pool.activate_pool()

    dataset.assert_not_called()


@pytest.mark.parametrize(
    'recursive, force, expected',
    [
        (False, False, ['zfs', 'destroy', 'tank/iocage/jails/one']),
        (True, False, ['zfs', 'destroy', '-r',
                       'tank/iocage/jails/one']),
        (False, True, ['zfs', 'destroy', '-f',
                       'tank/iocage/jails/one']),
        (True, True, ['zfs', 'destroy', '-r', '-f',
                      'tank/iocage/jails/one']),
    ],
)
def test_destroy_never_requests_clone_recursive_uppercase_r(
    recursive, force, expected
):
    with patch('iocage_lib.zfs.run', return_value=Mock(returncode=0)) as run:
        assert zfs.destroy_zfs_resource(
            'tank/iocage/jails/one', recursive, force
        ) is True

    run.assert_called_once_with(expected)
    assert '-R' not in expected
    assert '-Rf' not in expected


def test_destroy_propagates_zfs_dependent_clone_refusal():
    refusal = zfs.ZFSException(1, 'dataset has dependent clones')

    with patch('iocage_lib.zfs.run', side_effect=refusal):
        with pytest.raises(zfs.ZFSException) as error:
            zfs.destroy_zfs_resource(
                'tank/iocage/jails/one', recursive=True, force=True
            )

    assert error.value is refusal


def test_malformed_jail_cleanup_uses_exact_iocage_dataset():
    destroy = IOCDestroy.__new__(IOCDestroy)
    destroy.pool = 'tank'
    path = '/mnt/tank/iocage/jails/broken'

    with patch(
        'iocage_lib.ioc_destroy.iocage_lib.ioc_stop.IOCStop',
        side_effect=JailMissingConfiguration('missing config'),
    ) as stop, patch.object(
        destroy, '__destroy_parse_datasets__'
    ) as parse_datasets:
        destroy.destroy_jail(path)

    stop.assert_called_once_with('broken', path, silent=True)
    parse_datasets.assert_called_once_with('tank/iocage/jails/broken')


def test_destroy_jail_rejects_non_jail_dataset_path():
    destroy = IOCDestroy.__new__(IOCDestroy)
    destroy.pool = 'tank'

    with patch(
        'iocage_lib.ioc_destroy.iocage_lib.ioc_stop.IOCStop'
    ) as stop, patch.object(
        destroy, '__destroy_parse_datasets__'
    ) as parse_datasets:
        with pytest.raises(ValueError, match='Invalid jail dataset path'):
            destroy.destroy_jail('/mnt/tank/iocage/releases/15.1-RELEASE')

    stop.assert_not_called()
    parse_datasets.assert_not_called()


def test_destroy_jail_does_not_suppress_unexpected_stop_error():
    destroy = IOCDestroy.__new__(IOCDestroy)
    destroy.pool = 'tank'

    with patch(
        'iocage_lib.ioc_destroy.iocage_lib.ioc_stop.IOCStop',
        side_effect=KeyError('unexpected stop error'),
    ), patch.object(
        destroy, '__destroy_parse_datasets__'
    ) as parse_datasets:
        with pytest.raises(KeyError, match='unexpected stop error'):
            destroy.destroy_jail('/mnt/tank/iocage/jails/broken')

    parse_datasets.assert_not_called()


def test_fstab_validation_compares_encoded_jail_root():
    fstab = IOCFstab.__new__(IOCFstab)
    fstab.iocroot = '/mnt/tank pool/iocage'
    fstab.uuid = 'jail name'
    fstab.action = 'list'
    fstab.callback = None
    fstab.silent = True

    def encode(value):
        return value.replace(' ', r'\040')

    def decode(value):
        return value.replace(r'\040', ' ')

    encode_path = Mock(side_effect=encode)
    fstab.__fstab_encode__ = encode_path
    fstab.__fstab_decode__ = decode
    source = '/mnt/media source'
    destination = (
        '/mnt/tank pool/iocage/jails/jail name/root/media destination'
    )
    line = f'{encode(source)} {encode(destination)} nullfs rw 0 0'

    with patch(
        'iocage_lib.ioc_fstab.pathlib.Path.is_dir', return_value=True
    ):
        result = fstab.__validate_fstab__([line], mode='all')

    encode_path.assert_called_once_with(
        '/mnt/tank pool/iocage/jails/jail name/root'
    )
    assert result == {source: encode(destination)}


def test_image_export_enumerates_only_filesystems_below_target(tmp_path):
    images = tmp_path / 'images'
    images.mkdir()
    image = IOCImage.__new__(IOCImage)
    image.pool = 'tank'
    image.iocroot = str(tmp_path)
    image.date = '2026-08-26'
    image.callback = None
    image.silent = True
    list_process = Mock()
    list_process.communicate.return_value = (
        b'tank/iocage/jails/one\n', b''
    )

    with patch(
        'iocage_lib.ioc_image.iocage_lib.ioc_common.checkoutput'
    ), patch(
        'iocage_lib.ioc_image.iocage_lib.ioc_common.logit'
    ), patch(
        'iocage_lib.ioc_image.su.Popen', return_value=list_process
    ) as popen, patch('iocage_lib.ioc_image.su.check_call'):
        image.export_jail(
            'one', '/mnt/tank/iocage/jails/one', compression_algo='zip'
        )

    popen.assert_called_once_with(
        [
            'zfs', 'list', '-H', '-r', '-t', 'filesystem',
            '-o', 'name', 'tank/iocage/jails/one',
        ],
        stdout=-1,
        stderr=-1,
    )


class _RecordingStream:
    def __init__(self):
        self.chunks = [b'first', b'second', b'']
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        self.read_sizes.append(size)
        return self.chunks.pop(0)


class _FakeZipFile:
    def __init__(self, stream):
        self.stream = stream

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @staticmethod
    def namelist():
        return ['jail_2026-08-26']

    def open(self, name):
        assert name == 'jail_2026-08-26'
        return self.stream


def test_image_import_streams_bounded_chunks_to_zfs_recv():
    image = IOCImage.__new__(IOCImage)
    image.pool = 'tank'
    image.iocroot = '/mnt/tank/iocage'
    image.callback = None
    image.silent = True
    stream = _RecordingStream()
    archive = _FakeZipFile(stream)
    recv = Mock()
    recv.stdin = Mock()
    jail_json = Mock()
    jail_json.json_get_value.return_value = 'jail'

    with patch(
        'iocage_lib.ioc_image.os.path.exists', return_value=True
    ), patch(
        'iocage_lib.ioc_image.os.path.isfile', return_value=True
    ), patch(
        'iocage_lib.ioc_image.zipfile.ZipFile', return_value=archive
    ), patch(
        'iocage_lib.ioc_image.su.Popen', return_value=recv
    ) as popen, patch(
        'iocage_lib.ioc_image.iocage_lib.ioc_common.checkoutput'
    ), patch(
        'iocage_lib.ioc_image.iocage_lib.ioc_common.logit'
    ), patch(
        'iocage_lib.ioc_image.iocage_lib.ioc_json.IOCJson',
        return_value=jail_json,
    ), patch('iocage_lib.ioc_image.cache.reset'):
        image.import_jail(
            'jail', path='/images/jail_2026-08-26.zip'
        )

    popen.assert_called_once_with(
        ['zfs', 'recv', '-F', 'tank/iocage/jails/jail'], stdin=-1
    )
    assert stream.read_sizes == [10 * 1024 * 1024] * 3
    recv.stdin.write.assert_has_calls([call(b'first'), call(b'second')])
    assert recv.stdin.write.call_count == 2
    recv.communicate.assert_called_once_with()
