import io
import os
import tarfile

import pytest

import iocage_lib.ioc_fetch as ioc_fetch


def _add_file(archive, name, mode, contents=b'release fixture'):
    member = tarfile.TarInfo(name)
    member.mode = mode
    member.size = len(contents)
    archive.addfile(member, io.BytesIO(contents))


def _add_directory(archive, name, mode):
    member = tarfile.TarInfo(name)
    member.type = tarfile.DIRTYPE
    member.mode = mode
    archive.addfile(member)


def _add_link(
    archive, name, linkname, link_type=tarfile.SYMTYPE, mode=0o777
):
    member = tarfile.TarInfo(name)
    member.type = link_type
    member.linkname = linkname
    member.mode = mode
    archive.addfile(member)


def test_release_archive_extraction_preserves_modes_and_safe_links(tmp_path):
    archive_path = tmp_path / 'base.tar'
    destination = tmp_path / 'release'
    destination.mkdir()

    with tarfile.open(archive_path, 'w') as archive:
        _add_directory(archive, 'bin', 0o755)
        _add_file(archive, 'bin/setuid-tool', 0o4755)
        _add_file(archive, 'bin/setgid-tool', 0o2755)
        _add_file(archive, 'bin/executable', 0o755)
        _add_directory(archive, 'tmp', 0o1777)
        _add_directory(archive, 'var', 0o755)
        _add_directory(archive, 'var/empty', 0o700)
        _add_link(archive, 'bin/executable-link', 'executable')
        _add_link(
            archive,
            'bin/executable-hardlink',
            'bin/executable',
            tarfile.LNKTYPE,
            mode=0o755,
        )

    with tarfile.open(archive_path) as archive:
        archive.extractall(
            destination, filter=ioc_fetch._release_archive_filter
        )

    expected_modes = {
        'bin': 0o755,
        'bin/setuid-tool': 0o4755,
        'bin/setgid-tool': 0o2755,
        'bin/executable': 0o755,
        'tmp': 0o1777,
        'var': 0o755,
        'var/empty': 0o700,
    }
    for path, mode in expected_modes.items():
        assert os.stat(destination / path).st_mode & 0o7777 == mode

    link_path = destination / 'bin/executable-link'
    assert link_path.is_symlink()
    assert os.readlink(link_path) == 'executable'
    assert link_path.read_bytes() == b'release fixture'

    hardlink_path = destination / 'bin/executable-hardlink'
    assert hardlink_path.read_bytes() == b'release fixture'
    assert os.stat(hardlink_path).st_ino == os.stat(
        destination / 'bin/executable'
    ).st_ino


def test_release_archive_filter_rejects_path_traversal(tmp_path):
    archive_path = tmp_path / 'unsafe.tar'
    destination = tmp_path / 'release'
    destination.mkdir()

    with tarfile.open(archive_path, 'w') as archive:
        _add_file(archive, '../escape', 0o644)

    with tarfile.open(archive_path) as archive:
        with pytest.raises(tarfile.OutsideDestinationError):
            archive.extractall(
                destination, filter=ioc_fetch._release_archive_filter
            )

    assert not (tmp_path / 'escape').exists()


@pytest.mark.parametrize('link_type', [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_release_archive_filter_rejects_links_outside_destination(
    tmp_path, link_type
):
    archive_path = tmp_path / 'unsafe.tar'
    destination = tmp_path / 'release'
    destination.mkdir()

    with tarfile.open(archive_path, 'w') as archive:
        _add_link(archive, 'unsafe-link', '../escape', link_type)

    with tarfile.open(archive_path) as archive:
        with pytest.raises(tarfile.LinkOutsideDestinationError):
            archive.extractall(
                destination, filter=ioc_fetch._release_archive_filter
            )

    assert not (tmp_path / 'escape').exists()
    assert not (destination / 'unsafe-link').exists()


def test_release_archive_filter_allows_jail_root_absolute_symlink(tmp_path):
    archive_path = tmp_path / 'base.tar'
    destination = tmp_path / 'release'
    destination.mkdir()

    with tarfile.open(archive_path, 'w') as archive:
        _add_directory(archive, './etc', 0o755)
        _add_directory(archive, './usr', 0o755)
        _add_directory(archive, './usr/share', 0o755)
        _add_directory(archive, './usr/share/misc', 0o755)
        _add_file(
            archive,
            './usr/share/misc/termcap',
            0o444,
            b'FreeBSD termcap fixture',
        )
        _add_link(
            archive,
            './etc/termcap',
            '/usr/share/misc/termcap',
        )

    with tarfile.open(archive_path) as archive:
        archive.extractall(
            destination, filter=ioc_fetch._release_archive_filter
        )

    link_path = destination / 'etc/termcap'
    assert link_path.is_symlink()
    assert os.readlink(link_path) == '/usr/share/misc/termcap'
    assert (
        destination / 'usr/share/misc/termcap'
    ).read_bytes() == b'FreeBSD termcap fixture'


def test_release_archive_filter_rejects_write_through_absolute_symlink(
    tmp_path,
):
    archive_path = tmp_path / 'unsafe.tar'
    destination = tmp_path / 'release'
    outside = tmp_path / 'outside'
    destination.mkdir()
    outside.mkdir()

    with tarfile.open(archive_path, 'w') as archive:
        _add_directory(archive, 'link-parent', 0o755)
        _add_link(archive, 'link-parent/rooted', str(outside))
        _add_file(
            archive,
            'link-parent/rooted/escape',
            0o644,
        )

    with tarfile.open(archive_path) as archive:
        with pytest.raises(tarfile.OutsideDestinationError):
            archive.extractall(
                destination, filter=ioc_fetch._release_archive_filter
            )

    assert not (outside / 'escape').exists()


def test_release_archive_filter_rejects_absolute_hardlink(tmp_path):
    archive_path = tmp_path / 'unsafe.tar'
    destination = tmp_path / 'release'
    destination.mkdir()

    with tarfile.open(archive_path, 'w') as archive:
        _add_link(
            archive,
            'unsafe-link',
            '/etc/passwd',
            tarfile.LNKTYPE,
        )

    with tarfile.open(archive_path) as archive:
        with pytest.raises(tarfile.AbsoluteLinkError):
            archive.extractall(
                destination, filter=ioc_fetch._release_archive_filter
            )

    assert not (destination / 'unsafe-link').exists()


@pytest.mark.parametrize(
    'linkname',
    ['/usr/../etc/passwd', '//usr/share/misc/termcap', '/'],
)
def test_release_archive_filter_rejects_noncanonical_absolute_symlink(
    tmp_path, linkname
):
    archive_path = tmp_path / 'unsafe.tar'
    destination = tmp_path / 'release'
    destination.mkdir()

    with tarfile.open(archive_path, 'w') as archive:
        _add_link(archive, 'unsafe-link', linkname)

    with tarfile.open(archive_path) as archive:
        with pytest.raises(tarfile.AbsoluteLinkError):
            archive.extractall(
                destination, filter=ioc_fetch._release_archive_filter
            )

    assert not (destination / 'unsafe-link').exists()
