import os
import re
import requests

import iocage_lib.dataset as dataset

from iocage_lib.cache import cache
from iocage_lib.resource import IocageListableResource
from iocage_lib.ioc_fetch import (
    IOCFetch, FREEBSD_ARCHIVE_SERVER, FREEBSD_ARCHIVE_ROOT,
    archived_release_candidates, release_major,
)
from iocage_lib.ioc_common import (
    check_release_newer, get_host_release, sort_release,
)


def remote_release_index(url, required=True):
    """The ``XX.Y-RELEASE`` names a FreeBSD mirror index page lists.

    A mirror that cannot be read is an error with a message when required,
    and simply an empty list otherwise.
    """
    try:
        req = requests.get(url, timeout=10)
    except requests.RequestException as error:
        if required:
            raise RuntimeError(
                f'Could not list releases from {url}: {error}'
            ) from error
        return []
    if req.status_code != requests.codes.ok:
        if required:
            raise RuntimeError(
                f'Could not list releases from {url}: '
                f'HTTP {req.status_code}'
            )
        return []
    return re.findall(
        r'href="(\d[^"/]*RELEASE)/"', req.content.decode('utf-8')
    )


def remote_releases(machine, host_release):
    """Primary-mirror releases plus the archived ones it no longer lists."""
    primary = remote_release_index(
        f'https://download.freebsd.org/ftp/releases/{machine}/'
    )
    host_major = release_major(host_release)
    if host_major is None:
        return primary
    archived = remote_release_index(
        f'https://{FREEBSD_ARCHIVE_SERVER}/{FREEBSD_ARCHIVE_ROOT}/'
        f'{machine}/', required=False
    )
    return sort_release(
        primary + archived_release_candidates(primary, archived, host_major),
        fetch_releases=True,
    )


class Release(dataset.Dataset):

    def __init__(self, name, *args, **kwargs):
        if '/' not in name and cache.iocage_activated_dataset:
            name = os.path.join(cache.iocage_activated_dataset, 'releases', name)
        super().__init__(name, *args, **kwargs)
        if self.resource_name:
            self.name = self.resource_name.rsplit('/', 1)[-1]

    def __repr__(self):
        return str(self.name)

    def __str__(self):
        return str(self.name)


class ListableReleases(IocageListableResource):

    resource = Release

    def __init__(self, remote=False, eol_check=True):
        # We should abstract distribution and have eol checks live there in
        # the future probably plus release should be able to tell if it's eol
        # or not. Also perhaps we should think of a filter
        # interface.
        super().__init__()
        if self.dataset_path:
            self.dataset_path = os.path.join(self.dataset_path, 'releases')
        self.remote = remote
        self.eol_check = eol_check
        self.eol_list = []
        if eol_check and remote:
            # TODO: Please let's not use this in the future and look at
            # comments above
            self.eol_list = IOCFetch.__fetch_eol_check__()

    def __iter__(self):
        if self.remote:
            # TODO: Please abstract this in the future
            for release in filter(
                lambda r: (
                    r if not self.eol_check else r not in self.eol_list
                ) and not check_release_newer(
                    r, raise_error=False, major_only=True
                ),
                remote_releases(os.uname().machine, get_host_release())
            ):
                yield self.resource(release)
        else:
            for r in super().__iter__():
                yield r
