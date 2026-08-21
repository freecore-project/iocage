import pathlib
import types

import pytest

import iocage_lib.ioc_upgrade as ioc_upgrade


class _Recorder:
    """Captures the commands upgrade_basejail hands to SilentExec."""

    def __init__(self):
        self.commands = []

    def __call__(self, command, path, uuid=None, unjailed=False, **kwargs):
        self.commands.append(list(command))


def _upgrade(tmp_path, new_release, with_reference_tree, monkeypatch):
    iocroot = tmp_path / 'iocage'
    jail = iocroot / 'jails' / 'test'
    root = jail / 'root'
    release_root = iocroot / 'releases' / new_release / 'root'

    (root / 'var' / 'db' / 'etcupdate').mkdir(parents=True)
    (root / 'var' / 'spool' / 'mqueue').mkdir(parents=True)
    (release_root / 'usr' / 'src').mkdir(parents=True)
    (release_root / 'usr' / 'src' / 'Makefile').write_text('')
    (release_root / 'bin').mkdir(parents=True)

    if with_reference_tree:
        current = release_root / 'var' / 'db' / 'etcupdate' / 'current'
        (current / 'etc').mkdir(parents=True)
        (current / 'etc' / 'rc.subr').write_text('')

    upgrade = ioc_upgrade.IOCUpgrade.__new__(ioc_upgrade.IOCUpgrade)
    upgrade.iocroot = str(iocroot)
    upgrade.new_release = new_release
    upgrade.path = str(root)
    upgrade.uuid = 'test'
    upgrade.freebsd_version = '15.1-RELEASE-p3'
    upgrade.callback = None
    upgrade.silent = True

    recorder = _Recorder()
    monkeypatch.setattr(ioc_upgrade.iocage_lib.ioc_exec, 'SilentExec',
                        recorder)
    # names with trailing double underscores are not mangled
    monkeypatch.setattr(
        ioc_upgrade.IOCUpgrade, '__snapshot_jail__',
        lambda self: None, raising=False)
    monkeypatch.setattr(
        ioc_upgrade.IOCUpgrade, '__upgrade_replace_basejail_paths__',
        lambda self: None, raising=False)
    monkeypatch.setattr(
        ioc_upgrade.iocage_lib.ioc_common, 'get_jail_freebsd_version',
        lambda path, release: release)

    class _Json:
        def __init__(self, *args, **kwargs):
            pass

        def json_set_value(self, value):
            pass

    monkeypatch.setattr(ioc_upgrade.iocage_lib.ioc_json, 'IOCJson', _Json)

    upgrade.upgrade_basejail(snapshot=False)
    return recorder.commands


def _etcupdate_command(commands):
    for command in commands:
        if any(part.endswith('etcupdate') for part in command):
            return command
    raise AssertionError('etcupdate was never invoked')


def test_shipped_reference_tree_is_used_without_src(tmp_path, monkeypatch):
    """A release that ships var/db/etcupdate/current is applied with -t."""
    commands = _upgrade(tmp_path, '15.1-RELEASE', True, monkeypatch)
    etcupdate = _etcupdate_command(commands)

    assert '-t' in etcupdate
    assert '-s' not in etcupdate
    assert etcupdate[etcupdate.index('-t') + 1].endswith('.tar')
    # the read-only src nullfs mount is what broke 13.x -> 15.x upgrades
    assert not any(c and c[0] == 'mount_nullfs' for c in commands)
    assert any(c and c[0] == 'tar' for c in commands)


def test_release_without_reference_tree_falls_back_to_src(
    tmp_path, monkeypatch
):
    """Older releases keep the historic -s /usr/src behaviour."""
    commands = _upgrade(tmp_path, '13.4-RELEASE', False, monkeypatch)
    etcupdate = _etcupdate_command(commands)

    assert '-s' in etcupdate
    assert '-t' not in etcupdate
    assert any(c and c[0] == 'mount_nullfs' for c in commands)


def test_reference_tree_run_cleans_up_the_tarball(tmp_path, monkeypatch):
    """The staged tarball is removed instead of unmounting nothing."""
    commands = _upgrade(tmp_path, '15.1-RELEASE', True, monkeypatch)

    assert any(c[:2] == ['rm', '-f'] for c in commands)
    assert not any(c and c[0] == 'umount' for c in commands)
