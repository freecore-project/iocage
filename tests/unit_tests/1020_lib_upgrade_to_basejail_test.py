import importlib.util
import json
import os
import pathlib
from unittest import mock

import pytest
from click.testing import CliRunner

import iocage_lib.ioc_common as ioc_common
import iocage_lib.ioc_fstab
import iocage_lib.ioc_upgrade as ioc_upgrade
import iocage_lib.iocage as iocage
import iocage_lib.snapshot

NEW = '15.1-RELEASE'
SNAP = 'ioc_upgrade_2026-11-17'
BASEDIRS = [
    'bin', 'boot', 'lib', 'libexec', 'rescue', 'sbin', 'usr/bin',
    'usr/include', 'usr/lib', 'usr/libexec', 'usr/sbin', 'usr/share',
    'usr/libdata', 'usr/lib32',
]


class _Fstab:
    """Stands in for IOCFstab: lists what the test gave, records adds."""

    entries = []
    added = []

    def __init__(self, uuid, action, *args, **kwargs):
        if action == 'add':
            _Fstab.added.append(args[:4])

    def fstab_list(self):
        return list(enumerate(_Fstab.entries))


class _Snapshot:
    existing = set()

    def __init__(self, name):
        self.exists = name in _Snapshot.existing


@pytest.fixture
def jail(tmp_path, monkeypatch):
    """A thick jail and a fetched RELEASE, both on disk under tmp_path."""
    iocroot = tmp_path / 'iocage'
    root = iocroot / 'jails' / 'j' / 'root'
    release_root = iocroot / 'releases' / NEW / 'root'

    for bdir in BASEDIRS:
        (release_root / bdir).mkdir(parents=True)
        (root / bdir).mkdir(parents=True)
        (root / bdir / 'old').write_text('13.5')

    (root / 'var/db/etcupdate/current/etc').mkdir(parents=True)
    (root / 'etc').mkdir()
    (root / 'etc/rc.conf').write_text('sshd_enable="YES"\n')
    (root / 'usr/local/bin').mkdir(parents=True)
    (root / 'usr/local/bin/app').write_text('package')

    upgrade = ioc_upgrade.IOCUpgrade.__new__(ioc_upgrade.IOCUpgrade)
    upgrade.pool = 'tank'
    upgrade.iocroot = str(iocroot)
    upgrade.new_release = NEW
    upgrade.path = str(root)
    upgrade.uuid = 'j'
    upgrade.freebsd_version = '15.2-RELEASE'
    upgrade.date = '2026-11-17'
    upgrade.callback = None
    upgrade.silent = True

    _Fstab.entries = []
    _Fstab.added = []
    _Snapshot.existing = set()
    monkeypatch.setattr(iocage_lib.ioc_fstab, 'IOCFstab', _Fstab)
    monkeypatch.setattr(iocage_lib.snapshot, 'Snapshot', _Snapshot)
    monkeypatch.setattr(ioc_common, 'INTERACTIVE', False)

    return upgrade


def _tree(root):
    """Every path under root with its content, to prove nothing moved."""
    found = {}

    for directory, _dirs, files in os.walk(root):
        found[directory] = None

        for name in files:
            path = os.path.join(directory, name)
            with open(path) as f:
                found[path] = f.read()

    return found


def test_the_directory_list_is_the_one_a_new_basejail_gets():
    assert ioc_common.basejail_dirs('15.1-RELEASE') == BASEDIRS
    # HardenedBSD has no usr/lib32
    assert ioc_common.basejail_dirs('13-STABLE') == BASEDIRS[:-1]


def test_a_jail_that_can_be_converted_passes_the_check(jail):
    before = _tree(jail.iocroot)

    jail.__check_basejail_conversion__(BASEDIRS, SNAP)

    assert _tree(jail.iocroot) == before


def test_a_missing_release_is_refused(jail):
    jail.new_release = '15.9-RELEASE'

    with pytest.raises(RuntimeError, match='15.9-RELEASE is missing'):
        jail.__check_basejail_conversion__(BASEDIRS, SNAP)


def test_a_release_without_one_of_the_directories_is_refused(jail):
    os.rmdir(f'{jail.iocroot}/releases/{NEW}/root/usr/lib32')

    with pytest.raises(RuntimeError, match='has no usr/lib32'):
        jail.__check_basejail_conversion__(BASEDIRS, SNAP)


def test_a_jail_without_an_etcupdate_tree_is_refused(jail):
    os.rmdir(f'{jail.path}/var/db/etcupdate/current/etc')

    with pytest.raises(RuntimeError, match='etcupdate/current'):
        jail.__check_basejail_conversion__(BASEDIRS, SNAP)


def test_a_link_on_the_way_to_a_directory_is_refused(jail, tmp_path):
    """/usr as a link would take the emptying outside the jail."""
    outside = tmp_path / 'outside'
    (outside / 'bin').mkdir(parents=True)
    (outside / 'bin/keep').write_text('host file')
    os.rename(f'{jail.path}/usr', f'{jail.path}/usr.real')
    os.symlink(outside, f'{jail.path}/usr')

    with pytest.raises(RuntimeError, match='usr is not a directory'):
        jail.__check_basejail_conversion__(BASEDIRS, SNAP)

    assert (outside / 'bin/keep').read_text() == 'host file'


def test_a_directory_the_jail_lacks_is_not_an_obstacle(jail):
    os.remove(f'{jail.path}/usr/lib32/old')
    os.rmdir(f'{jail.path}/usr/lib32')

    jail.__check_basejail_conversion__(BASEDIRS, SNAP)
    jail_json = mock.Mock()

    with mock.patch.object(
        ioc_upgrade.iocage_lib.ioc_json, 'IOCJson', return_value=jail_json
    ):
        jail.__convert_to_basejail__(BASEDIRS)

    assert os.listdir(f'{jail.path}/usr/lib32') == []


@pytest.mark.parametrize('where', [
    'usr/share',            # on a base directory
    'usr/share/examples',   # inside one
    'usr',                  # above some
])
def test_a_mount_that_meets_a_base_directory_is_refused(jail, where):
    _Fstab.entries = [
        ['/mnt/tank/media', f'{jail.path}/media', 'nullfs', 'ro', '0', '0'],
        ['/mnt/tank/x', f'{jail.path}/{where}/', 'nullfs', 'ro', '0', '0'],
    ]

    with pytest.raises(RuntimeError, match='Remove that fstab entry'):
        jail.__check_basejail_conversion__(BASEDIRS, SNAP)


def test_mounts_elsewhere_in_the_jail_are_no_obstacle(jail):
    _Fstab.entries = [
        ['/mnt/tank/media', f'{jail.path}/media', 'nullfs', 'ro', '0', '0'],
        ['/mnt/tank/www', f'{jail.path}/usr/local/www', 'nullfs', 'rw', '0',
         '0'],
        # not usr/lib: only the name starts the same
        ['/mnt/tank/l', f'{jail.path}/usr/lib64', 'nullfs', 'ro', '0', '0'],
    ]

    jail.__check_basejail_conversion__(BASEDIRS, SNAP)


def test_an_existing_snapshot_of_that_name_is_refused(jail):
    _Snapshot.existing = {f'tank/iocage/jails/j@{SNAP}'}

    with pytest.raises(RuntimeError, match='already exists'):
        jail.__check_basejail_conversion__(BASEDIRS, SNAP)


def test_conversion_empties_mounts_and_records_the_basejail(jail):
    jail_json = mock.Mock()

    with mock.patch.object(
        ioc_upgrade.iocage_lib.ioc_json, 'IOCJson', return_value=jail_json
    ) as json_class:
        jail.__convert_to_basejail__(BASEDIRS)

    for bdir in BASEDIRS:
        assert os.listdir(f'{jail.path}/{bdir}') == []

    # what is not a base directory is the jail's own and stays
    with open(f'{jail.path}/etc/rc.conf') as f:
        assert f.read() == 'sshd_enable="YES"\n'
    with open(f'{jail.path}/usr/local/bin/app') as f:
        assert f.read() == 'package'

    assert _Fstab.added == [
        (
            f'{jail.iocroot}/releases/{NEW}/root/{bdir}',
            f'{jail.path}/{bdir}', 'nullfs', 'ro',
        ) for bdir in BASEDIRS
    ]
    json_class.assert_called_once_with(
        f'{jail.iocroot}/jails/j', silent=True)
    jail_json.json_set_value.assert_called_once_with('basejail=1')


def _orchestrated(jail, monkeypatch, fail=None, undo_fails=False):
    """Runs upgrade_to_basejail with every step replaced by a recorder."""
    steps = []

    def step(name, result=None):
        def run(self, *args, **kwargs):
            steps.append((name, args, kwargs))

            if fail == name:
                raise SystemExit(1)

            return result

        return run

    def undo(self, *args, **kwargs):
        steps.append(('undo', args, kwargs))

        if undo_fails:
            raise RuntimeError('dataset is busy')

    def start(uuid, path, silent=False):
        steps.append(('start', (uuid, path), {'silent': silent}))

        if fail == 'start':
            raise SystemExit(1)

    for name, replacement in (
        ('__check_basejail_conversion__', step('check')),
        ('__snapshot_jail__', step('snapshot')),
        ('__convert_to_basejail__', step('convert')),
        ('upgrade_basejail', step('upgrade', '15.1-RELEASE-p6')),
        ('__undo_basejail_conversion__', undo),
    ):
        monkeypatch.setattr(
            ioc_upgrade.IOCUpgrade, name, replacement, raising=False)

    import iocage_lib.ioc_start
    monkeypatch.setattr(iocage_lib.ioc_start, 'IOCStart', start)

    messages = []
    real_logit = ioc_common.logit

    def logit(content, **kwargs):
        messages.append((content['level'], content['message']))

        if content['level'] == 'EXCEPTION':
            real_logit(content, **kwargs)

    monkeypatch.setattr(ioc_common, 'logit', logit)

    return steps, messages


def test_snapshot_comes_before_the_first_change(jail, monkeypatch):
    steps, messages = _orchestrated(jail, monkeypatch)

    assert jail.upgrade_to_basejail() == '15.1-RELEASE-p6'
    assert [s[0] for s in steps] == [
        'check', 'snapshot', 'convert', 'start', 'upgrade',
    ]
    # the jail is started from its own directory, not from root/
    assert steps[3][1] == ('j', f'{jail.iocroot}/jails/j')
    # one snapshot: the basejail upgrade is told to use ours for its way back
    assert steps[4][2] == {'snapshot': False, 'snap_name': SNAP}
    assert messages == []


def test_a_refused_jail_gets_no_snapshot_and_no_change(jail, monkeypatch):
    steps, _messages = _orchestrated(jail, monkeypatch, fail='check')

    with pytest.raises(SystemExit):
        jail.upgrade_to_basejail()

    assert [s[0] for s in steps] == ['check']


@pytest.mark.parametrize('failing', ['convert', 'start', 'upgrade'])
def test_a_failure_after_the_snapshot_rolls_the_jail_back(
    jail, monkeypatch, failing
):
    steps, messages = _orchestrated(jail, monkeypatch, fail=failing)

    # SystemExit is what a failed step raises on the command line
    with pytest.raises(SystemExit):
        jail.upgrade_to_basejail()

    assert steps[-1] == ('undo', (BASEDIRS, SNAP), {})
    assert messages == [(
        'ERROR',
        f'j was rolled back to the snapshot {SNAP}. It is not a basejail'
        ' and was not upgraded.',
    )]


def test_a_failed_rollback_names_the_snapshot_and_keeps_the_first_error(
    jail, monkeypatch
):
    _steps, messages = _orchestrated(
        jail, monkeypatch, fail='upgrade', undo_fails=True)

    with pytest.raises(SystemExit):
        jail.upgrade_to_basejail()

    assert len(messages) == 1
    assert 'Rolling j back failed: dataset is busy' in messages[0][1]
    assert f'iocage rollback -n {SNAP} j' in messages[0][1]


def test_hardenedbsd_is_refused_before_anything_else(jail, monkeypatch):
    steps, _messages = _orchestrated(jail, monkeypatch)
    jail.freebsd_version = '13-STABLE-HBSD'

    with pytest.raises(RuntimeError, match='HardenedBSD'):
        jail.upgrade_to_basejail()

    assert steps == []


def test_undo_stops_unmounts_and_rolls_back(jail, monkeypatch):
    calls = []
    jail_api = mock.Mock()
    jail_api.stop.side_effect = lambda: calls.append('stop')
    jail_api.rollback.side_effect = lambda name: calls.append(
        f'rollback {name}')
    monkeypatch.setattr(
        ioc_upgrade.su, 'run',
        lambda command, **kwargs: calls.append(' '.join(command)))

    with mock.patch.object(iocage, 'IOCage', return_value=jail_api):
        jail.__undo_basejail_conversion__(BASEDIRS, SNAP)

    assert calls == ['stop'] + [
        f'umount -f {jail.path}/{bdir}' for bdir in BASEDIRS
    ] + [f'rollback {SNAP}']


def _upgrade(tmp_path, basejail, running, to_basejail):
    """IOCage.upgrade() with the jail, its start and the upgrader faked."""
    jail_path = tmp_path / 'j'
    jail_path.mkdir()
    (jail_path / 'config.json').write_text(json.dumps({'type': 'jail'}))

    instance = iocage.IOCage.__new__(iocage.IOCage)
    instance.iocroot = ''
    instance.jail = 'j'
    instance.jails = {}
    instance.callback = None
    instance.silent = False
    instance.rc = False
    instance._all = False
    instance.skip_jails = False
    instance.is_depend = False
    instance.__check_jail_existence__ = mock.Mock(
        return_value=('j', str(jail_path)))
    instance.list = mock.Mock(return_value=(running, '7' if running else None))
    instance.stop = mock.Mock()

    config = mock.Mock()
    config.json_get_value.return_value = {
        'release': '13.5-RELEASE-p2', 'type': 'jail', 'basejail': basejail,
    }
    messages = []

    def logit(content, **_):
        if content['level'] == 'EXCEPTION':
            raise RuntimeError(content['message'])

        messages.append(content['message'])

    with mock.patch.object(
        iocage.ioc_json, 'IOCJson', return_value=config,
    ), mock.patch.object(
        iocage.ioc_common, 'check_release_newer',
    ), mock.patch.object(
        iocage.ioc_common, 'logit', side_effect=logit,
    ), mock.patch.object(
        iocage.ioc_start, 'IOCStart',
    ) as start, mock.patch.object(
        iocage.ioc_upgrade, 'IOCUpgrade',
    ) as upgrader:
        for method in ('upgrade_jail', 'upgrade_basejail',
                       'upgrade_to_basejail'):
            getattr(upgrader.return_value, method).return_value = \
                '15.1-RELEASE-p6'

        try:
            instance.upgrade(NEW, to_basejail=to_basejail)
            error = None
        except RuntimeError as e:
            error = str(e)

    used = [
        method for method in ('upgrade_jail', 'upgrade_basejail',
                              'upgrade_to_basejail')
        if getattr(upgrader.return_value, method).called
    ]

    return used, start.called, instance.stop.called, messages, error


def test_without_the_flag_a_jail_is_upgraded_as_before(tmp_path):
    used, started, stopped, messages, error = _upgrade(
        tmp_path, basejail=0, running=False, to_basejail=False)

    assert (used, started, stopped, error) == (
        ['upgrade_jail'], True, True, None)
    assert 'is now a basejail' not in messages[-1]


def test_with_the_flag_a_stopped_jail_is_converted(tmp_path):
    used, started, stopped, messages, error = _upgrade(
        tmp_path, basejail=0, running=False, to_basejail=True)

    # upgrade() does not start the jail here: it has to be converted first,
    # and the conversion starts it. It is stopped again at the end.
    assert (used, started, stopped, error) == (
        ['upgrade_to_basejail'], False, True, None)
    assert 'j successfully upgraded from 13.5-RELEASE-p2 to' \
        ' 15.1-RELEASE-p6!' in messages[-1]
    assert 'j is now a basejail.' in messages[-1]


def test_with_the_flag_a_running_jail_is_refused(tmp_path):
    used, started, stopped, _messages, error = _upgrade(
        tmp_path, basejail=0, running=True, to_basejail=True)

    assert (used, started, stopped) == ([], False, False)
    assert error == 'Please stop j before converting it to a basejail.'


@pytest.mark.parametrize('running', [False, True])
def test_the_flag_changes_nothing_for_a_basejail(tmp_path, running):
    used, started, stopped, messages, error = _upgrade(
        tmp_path, basejail=1, running=running, to_basejail=True)

    assert (used, started, stopped, error) == (
        ['upgrade_basejail'], not running, not running, None)
    assert 'is now a basejail' not in messages[-1]


def _upgrade_all(to_basejail):
    """IOCage.upgrade() as `iocage upgrade ALL` reaches it."""
    instance = iocage.IOCage.__new__(iocage.IOCage)
    instance.jail = 'ALL'
    instance.jails = {'a': '/iocage/jails/a', 'b': '/iocage/jails/b'}
    instance.callback = None
    instance.silent = False
    instance._all = True
    instance.__check_jail_existence__ = mock.Mock()
    upgraded = []

    def logit(content, **_):
        if content['level'] == 'EXCEPTION':
            raise RuntimeError(content['message'])

    def upgrade_one(release, *args, **kwargs):
        upgraded.append((instance.jail, release, args, kwargs))

    with mock.patch.object(iocage.ioc_common, 'logit', side_effect=logit):
        try:
            if to_basejail:
                instance.upgrade(NEW, to_basejail=True)
            else:
                # the per-jail pass: upgrade_all() calls upgrade() again
                real_upgrade = instance.upgrade
                instance.upgrade = upgrade_one
                real_upgrade(NEW)
            error = None
        except RuntimeError as e:
            error = str(e)

    return upgraded, instance.__check_jail_existence__.called, error


def test_all_with_the_flag_is_refused_before_any_jail():
    upgraded, looked_at_a_jail, error = _upgrade_all(to_basejail=True)

    assert (upgraded, looked_at_a_jail) == ([], False)
    assert error == ('A jail is converted to a basejail one at a time. '
                     'Name the jail instead of ALL.')


def test_all_without_the_flag_upgrades_every_jail_as_before():
    upgraded, _looked_at_a_jail, error = _upgrade_all(to_basejail=False)

    assert error is None
    # no flag reaches the single jails
    assert upgraded == [('a', NEW, (), {}), ('b', NEW, (), {})]


@pytest.mark.parametrize('arguments, expected', [
    (['j', '-r', NEW], False),
    (['j', '-r', NEW, '--basejail'], True),
    (['j', '-b', '-r', NEW], True),
])
def test_the_command_line_passes_the_flag_on(arguments, expected):
    # by path: importing the iocage_cli package takes over the terminal
    spec = importlib.util.spec_from_file_location(
        '_upgrade_to_basejail_test_cli',
        pathlib.Path(__file__).parents[2] / 'iocage_cli' / 'upgrade.py')
    cli_upgrade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli_upgrade)

    with mock.patch.object(cli_upgrade.ioc, 'IOCage') as api:
        result = CliRunner().invoke(cli_upgrade.cli, arguments)

    assert result.exit_code == 0, result.output
    api.assert_called_once_with(jail='j', skip_jails=True)
    api.return_value.upgrade.assert_called_once_with(
        NEW, to_basejail=expected)
