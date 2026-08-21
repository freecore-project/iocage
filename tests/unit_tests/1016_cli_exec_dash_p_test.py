import importlib.util
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner


class FakeIOCage:

    calls = []

    def __init__(self, *args, **kwargs):
        self.jail = kwargs.get('jail')

    def exec(self, command, host_user, jail_user, **kwargs):
        self.calls.append((self.jail, list(command), kwargs))


@pytest.fixture
def exec_cli(monkeypatch):
    common = types.ModuleType('iocage_lib.ioc_common')
    common.logit = lambda data, **kwargs: None

    iocage = types.ModuleType('iocage_lib.iocage')
    iocage.IOCage = FakeIOCage

    package = types.ModuleType('iocage_lib')
    package.__path__ = []
    package.ioc_common = common
    package.iocage = iocage

    monkeypatch.setitem(sys.modules, 'iocage_lib', package)
    monkeypatch.setitem(sys.modules, 'iocage_lib.ioc_common', common)
    monkeypatch.setitem(sys.modules, 'iocage_lib.iocage', iocage)

    path = Path(__file__).parents[2] / 'iocage_cli' / 'exec.py'
    spec = importlib.util.spec_from_file_location('_exec_dash_p_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    FakeIOCage.calls = []
    return module.cli


# the internal development record: since 1.13 (upstream 6518661) exec claimed -p as
# the short form of --keep_proxy. Options iocage knows are parsed even
# after the jail name, so `iocage exec J mkdir -p DIR` ran `mkdir DIR` and
# passed the host's proxy variables into the jail. 13.3's exec has no -p,
# so it reached the jail command.
ECHO_PROXY = 'echo "$http_proxy"'


@pytest.mark.parametrize('argv,command', [
    (['J', 'mkdir', '-p', '/tmp/a/b'], ['mkdir', '-p', '/tmp/a/b']),
    (['J', 'sh', '-c', ECHO_PROXY, '-p'], ['sh', '-c', ECHO_PROXY, '-p']),
    (['J', 'cp', '-p', 'a', 'b'], ['cp', '-p', 'a', 'b']),
])
def test_dash_p_reaches_the_jail_command(exec_cli, argv, command):
    result = CliRunner().invoke(exec_cli, argv)

    assert result.exit_code == 0, result.exception
    jail, ran, kwargs = FakeIOCage.calls[-1]
    assert (jail, ran) == ('J', command)
    assert kwargs['keep_proxy'] is False


def test_keep_proxy_long_option_still_passes_the_proxy(exec_cli):
    result = CliRunner().invoke(exec_cli, ['--keep_proxy', 'J', 'env'])

    assert result.exit_code == 0, result.exception
    jail, ran, kwargs = FakeIOCage.calls[-1]
    assert (jail, ran) == ('J', ['/bin/sh', '-c', 'env'])
    assert kwargs['keep_proxy'] is True
