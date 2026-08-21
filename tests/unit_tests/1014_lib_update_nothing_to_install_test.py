import json
from unittest import mock

import pytest

import iocage_lib.ioc_exceptions as ioc_exceptions
import iocage_lib.ioc_fetch as ioc_fetch
import iocage_lib.iocage as iocage


def _iocage_without_init(jail='j'):
    instance = iocage.IOCage.__new__(iocage.IOCage)
    instance.iocroot = ''
    instance.jail = jail
    instance.jails = {}
    instance.callback = None
    instance.silent = False
    instance.rc = False
    instance._all = False
    instance.skip_jails = False
    instance.is_depend = False
    return instance


def test_command_output_is_text_logit_can_join():
    error = ioc_exceptions.CommandFailed([b'first line\n', b'second\n'])

    assert ioc_fetch._command_output(error) == 'first line\nsecond\n'


def test_install_link_is_the_one_freebsd_update_checks():
    # BDHASH=`echo ${BASEDIR} | sha256 -q`, value from the shell
    basedir = '/mnt/tank/iocage/jails/j/root'

    assert ioc_fetch._freebsd_update_install_link(basedir) == (
        basedir + '/var/db/freebsd-update/'
        '0509007c7727eb4e5b3303462d7757289b23eedb0cfbcdb00b1ae19e72aa50e5'
        '-install'
    )


@pytest.mark.parametrize('installed, reported', [
    (False, 'j is already at the latest patch level.'),
    (True, 'j updates have been applied successfully.'),
])
def test_update_reports_what_freebsd_update_did(tmp_path, installed,
                                                reported):
    jail_path = tmp_path / 'j'
    jail_path.mkdir()
    (jail_path / 'config.json').write_text(json.dumps({'type': 'jail'}))
    instance = _iocage_without_init()
    instance.__check_jail_existence__ = mock.Mock(
        return_value=('j', str(jail_path))
    )
    instance.list = mock.Mock(return_value=(True, '7'))
    instance.snapshot = mock.Mock()
    config = mock.Mock()
    config.json_get_value.return_value = {
        'release': '15.1-RELEASE-p4', 'type': 'jail', 'basejail': 0,
    }
    messages = []

    with mock.patch.object(
        iocage.ioc_json, 'IOCJson', return_value=config,
    ), mock.patch.object(
        iocage.ioc_common, 'checkoutput', return_value='15.1-RELEASE-p4',
    ), mock.patch.object(iocage.ioc_fetch, 'IOCFetch') as fetch, \
            mock.patch.object(
                iocage.ioc_common, 'logit',
                side_effect=lambda content, **_: messages.append(
                    content['message'].strip()
                ),
            ):
        fetch.return_value.fetch_update.return_value = installed
        instance.update()

    assert reported in messages
    assert ('Updated jail successfully.' in messages) is installed
