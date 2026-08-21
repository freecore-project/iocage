import os
import tarfile

import pytest

import iocage_lib.ioc_fetch as ioc_fetch


@pytest.mark.parametrize('mode', [0o1777, 0o4755, 0o2755])
def test_release_archive_filter_preserves_modes(tmp_path, mode):
    member = tarfile.TarInfo('member')
    member.mode = mode

    filtered = ioc_fetch._release_archive_filter(member, str(tmp_path))

    assert filtered.mode == mode


def test_release_archive_extraction_preserves_temp_directory_mode(tmp_path):
    archive = tmp_path / 'base.tar'
    destination = tmp_path / 'release'
    destination.mkdir()

    with tarfile.open(archive, 'w') as output:
        member = tarfile.TarInfo('tmp')
        member.type = tarfile.DIRTYPE
        member.mode = 0o1777
        output.addfile(member)

    with tarfile.open(archive) as source:
        source.extractall(
            destination,
            filter=ioc_fetch._release_archive_filter,
        )

    assert os.stat(destination / 'tmp').st_mode & 0o7777 == 0o1777


def test_release_archive_filter_rejects_path_traversal(tmp_path):
    member = tarfile.TarInfo('../escape')

    with pytest.raises(tarfile.OutsideDestinationError):
        ioc_fetch._release_archive_filter(member, str(tmp_path))
