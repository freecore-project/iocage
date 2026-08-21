from unittest import mock

import pytest

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


@pytest.mark.parametrize('jail_has_pkg', [True, False])
def test_iocage_pkg_runs_the_jails_own_pkg_when_it_has_one(tmp_path,
                                                           jail_has_pkg):
    jail_path = tmp_path / 'j'
    (jail_path / 'root/usr/local/sbin').mkdir(parents=True)
    if jail_has_pkg:
        (jail_path / 'root/usr/local/sbin/pkg').write_text('')
    instance = _iocage_without_init()
    instance.__check_jail_existence__ = mock.Mock(
        return_value=('j', str(jail_path))
    )
    instance.list = mock.Mock(return_value=(True, '9'))
    props = {
        'exec_clean': False, 'ip4_addr': 'lo0|127.0.42.1', 'ip6_addr': 'none',
        'dhcp': False, 'nat': False,
    }
    instance.get = mock.Mock(side_effect=props.__getitem__)

    with mock.patch.object(iocage.ioc_exec, 'InteractiveExec') as exec_:
        instance.exec(['delete', 'figlet'], unjailed=True)

    command, = exec_.call_args.args[:1]
    options = exec_.call_args.kwargs
    if jail_has_pkg:
        assert command == ['/usr/local/sbin/pkg', 'delete', 'figlet']
        assert options['unjailed'] is False
        assert options['keep_proxy'] is True
    else:
        assert command == ['pkg', '-j', '9', 'delete', 'figlet']
        assert options['unjailed'] is True
        assert options['keep_proxy'] is False
