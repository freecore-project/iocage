"""the internal development record: EOL releases withdrawn from
download.freebsd.org are fetched from archive.freebsd.org/old-releases,
and listed beside the primary mirror's releases, without ever shadowing
a live release or second-guessing a user-supplied mirror."""
import pytest
import requests

import iocage_lib.ioc_fetch as ioc_fetch
import iocage_lib.release as release


PRIMARY = ['14.4-RELEASE', '14.5-RELEASE', '15.0-RELEASE', '15.1-RELEASE']
ARCHIVE = [
    '5.1-RELEASE', '5.2.1-RELEASE', '9.3-RELEASE', '12.4-RELEASE',
    '13.0-RELEASE', '13.1-RELEASE', '13.2-RELEASE', '13.3-RELEASE',
    '13.4-RELEASE', '13.5-RELEASE', '14.0-RELEASE', '14.1-RELEASE',
    '14.2-RELEASE', '14.3-RELEASE', '14.4-RELEASE', '14.5-RELEASE',
    '15.0-RELEASE', '15.1-RELEASE',
]

# The shape of both mirrors' index pages (nginx autoindex), one entry per line.
INDEX_HTML = '''<html><body><h1>Index of /old-releases/amd64/</h1><hr><pre>
<a href="../">../</a>
<a href="13.3-RELEASE/">13.3-RELEASE/</a>          10-Mar-2024 08:00    -
<a href="14.4-RELEASE/">14.4-RELEASE/</a>          20-Aug-2026 08:00    -
<a href="ISO-IMAGES/">ISO-IMAGES/</a>              20-Aug-2026 08:00    -
<a href="README.TXT">README.TXT</a>                20-Aug-2026 08:00  1234
</pre><hr></body></html>'''


class Response:
    def __init__(self, status_code, content=b''):
        self.status_code = status_code
        self.content = content


def responder(table):
    """A stand-in for requests.get answering by URL; unknown URLs are 404."""
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        answer = table.get(url, 404)
        if isinstance(answer, Exception):
            raise answer
        return Response(answer) if isinstance(answer, int) else answer
    get.calls = calls
    return get


@pytest.mark.parametrize('value, host', [
    ('download.freebsd.org', 'download.freebsd.org'),
    ('https://download.freebsd.org', 'download.freebsd.org'),
    ('HTTP://Download.FreeBSD.org/', 'download.freebsd.org'),
    ('https://archive.freebsd.org/old-releases', 'archive.freebsd.org'),
    ('mirror.example.org', 'mirror.example.org'),
])
def test_server_host_strips_scheme_path_and_case(value, host):
    assert ioc_fetch.server_host(value) == host


def test_only_the_two_freebsd_hosts_are_freebsd_mirrors():
    assert ioc_fetch.is_freebsd_mirror('https://download.freebsd.org')
    assert ioc_fetch.is_freebsd_mirror('http://download.freebsd.org')
    assert ioc_fetch.is_freebsd_mirror('archive.freebsd.org')
    assert not ioc_fetch.is_freebsd_mirror('https://mirror.example.org')


@pytest.mark.parametrize('name, major', [
    ('13.3-RELEASE', 13), ('5.2.1-RELEASE', 5), ('15.1-RELEASE-p3', 15),
    ('garbage', None), ('', None),
])
def test_release_major(name, major):
    assert ioc_fetch.release_major(name) == major


def test_archived_candidates_fill_the_gap_below_the_primary_only():
    got = ioc_fetch.archived_release_candidates(PRIMARY, ARCHIVE, 15)
    # 13.x and the 14.x the primary dropped; nothing the primary still lists,
    # nothing older than two majors below the host, nothing above the host.
    assert got == [
        '13.0-RELEASE', '13.1-RELEASE', '13.2-RELEASE', '13.3-RELEASE',
        '13.4-RELEASE', '13.5-RELEASE', '14.0-RELEASE', '14.1-RELEASE',
        '14.2-RELEASE', '14.3-RELEASE',
    ]


def test_archived_candidates_never_shadow_or_exceed_the_host():
    assert '15.1-RELEASE' not in ioc_fetch.archived_release_candidates(
        PRIMARY, ARCHIVE, 15
    )
    # A 14.x host does not get 15.x from the archive either.
    got = ioc_fetch.archived_release_candidates(['14.5-RELEASE'], ARCHIVE, 14)
    assert got[0] == '12.4-RELEASE' and got[-1] == '14.4-RELEASE'
    assert not any(r.startswith('15.') for r in got)
    assert ioc_fetch.archived_release_candidates(PRIMARY, [], 15) == []


def test_fallback_moves_to_the_archive_only_after_the_primary_says_404():
    get = responder({
        'https://download.freebsd.org/ftp/releases/amd64/13.3-RELEASE/': 404,
        'https://archive.freebsd.org/old-releases/amd64/13.3-RELEASE/': 200,
    })
    server, root_dir, archived = ioc_fetch.archive_fallback(
        'https://download.freebsd.org', 'ftp/releases/amd64',
        '13.3-RELEASE', 'amd64', get=get
    )
    assert (server, root_dir, archived) == (
        'https://archive.freebsd.org', 'old-releases/amd64', True
    )
    assert get.calls == [
        'https://download.freebsd.org/ftp/releases/amd64/13.3-RELEASE/',
        'https://archive.freebsd.org/old-releases/amd64/13.3-RELEASE/',
    ]


def test_fallback_leaves_a_live_release_on_the_primary():
    get = responder({
        'https://download.freebsd.org/ftp/releases/amd64/15.1-RELEASE/': 200,
    })
    assert ioc_fetch.archive_fallback(
        'https://download.freebsd.org', 'ftp/releases/amd64',
        '15.1-RELEASE', 'amd64', get=get
    ) == ('https://download.freebsd.org', 'ftp/releases/amd64', False)
    assert len(get.calls) == 1  # the archive was never asked


def test_fallback_stays_put_when_the_archive_lacks_it_too():
    get = responder({})  # everything 404
    assert ioc_fetch.archive_fallback(
        'http://download.freebsd.org', 'ftp/releases/amd64',
        '13.9-RELEASE', 'amd64', get=get
    ) == ('http://download.freebsd.org', 'ftp/releases/amd64', False)


@pytest.mark.parametrize('server, root_dir', [
    ('https://mirror.example.org', 'ftp/releases/amd64'),   # own server
    ('https://download.freebsd.org', 'my/tree'),            # own root_dir
    ('https://download.freebsd.org', None),                 # not resolved yet
])
def test_fallback_never_second_guesses_an_override(server, root_dir):
    get = responder({})
    assert ioc_fetch.archive_fallback(
        server, root_dir, '13.3-RELEASE', 'amd64', get=get
    ) == (server, root_dir, False)
    assert get.calls == []


def test_fallback_treats_a_network_error_as_no_answer():
    get = responder({
        'https://download.freebsd.org/ftp/releases/amd64/13.3-RELEASE/':
            requests.ConnectionError('mirror unreachable'),
    })
    assert ioc_fetch.archive_fallback(
        'https://download.freebsd.org', 'ftp/releases/amd64',
        '13.3-RELEASE', 'amd64', get=get
    ) == ('https://download.freebsd.org', 'ftp/releases/amd64', False)


def test_remote_index_reads_only_release_directories(monkeypatch):
    monkeypatch.setattr(
        release.requests, 'get',
        lambda url, **kw: Response(200, INDEX_HTML.encode('utf-8')),
    )
    assert release.remote_release_index('https://x/') == [
        '13.3-RELEASE', '14.4-RELEASE'
    ]


def test_remote_index_failure_is_an_error_only_when_required(monkeypatch):
    monkeypatch.setattr(
        release.requests, 'get', lambda url, **kw: Response(503)
    )
    with pytest.raises(RuntimeError, match='HTTP 503'):
        release.remote_release_index('https://x/')
    assert release.remote_release_index('https://x/', required=False) == []

    def boom(url, **kw):
        raise requests.ConnectionError('down')
    monkeypatch.setattr(release.requests, 'get', boom)
    with pytest.raises(RuntimeError, match='down'):
        release.remote_release_index('https://x/')
    assert release.remote_release_index('https://x/', required=False) == []


def test_remote_releases_merge_the_archive_behind_the_primary(monkeypatch):
    seen = []

    def index(url, required=True):
        seen.append((url, required))
        if 'archive.freebsd.org' in url:
            return list(ARCHIVE)
        return list(PRIMARY)
    monkeypatch.setattr(release, 'remote_release_index', index)
    got = release.remote_releases('amd64', '15.1-RELEASE')
    # Version order, the primary's and the archive's releases interleaved.
    assert got == [
        '13.0-RELEASE', '13.1-RELEASE', '13.2-RELEASE', '13.3-RELEASE',
        '13.4-RELEASE', '13.5-RELEASE', '14.0-RELEASE', '14.1-RELEASE',
        '14.2-RELEASE', '14.3-RELEASE', '14.4-RELEASE', '14.5-RELEASE',
        '15.0-RELEASE', '15.1-RELEASE',
    ]
    assert seen == [
        ('https://download.freebsd.org/ftp/releases/amd64/', True),
        ('https://archive.freebsd.org/old-releases/amd64/', False),
    ]


def test_remote_releases_without_a_parsable_host_is_the_primary_alone(
    monkeypatch
):
    monkeypatch.setattr(
        release, 'remote_release_index',
        lambda url, required=True: list(PRIMARY),
    )
    assert release.remote_releases('amd64', 'weird') == PRIMARY
