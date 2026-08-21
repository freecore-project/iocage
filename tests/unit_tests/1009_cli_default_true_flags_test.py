import importlib.util
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner


class FakeTexttable:

    def __init__(self, *args, **kwargs):
        self.rows = []

    def add_row(self, row):
        self.rows.append(row)

    def add_rows(self, rows, header=True):
        self.rows.extend(rows)

    def header(self, row):
        self.rows.append(row)

    def set_cols_dtype(self, dtypes):
        return None

    def draw(self):
        return 'TABLE'


class FakeIOCage:

    calls = []

    def __init__(self, *args, **kwargs):
        self.jail = kwargs.get('jail')

    def df(self):
        return [['demo', '1.00x', 'none', 'none', '1G', '2G']]

    def fetch(self, *args, **kwargs):
        self.calls.append(('fetch', kwargs))
        return ['15.1-RELEASE']

    def fstab(self, *args, **kwargs):
        self.calls.append(('fstab', kwargs))
        if kwargs['header']:
            return 'TABLE'
        return [(0, ('source', 'destination', 'nullfs', 'ro', '0', '0'))]

    def get(self, prop, recursive=False, **kwargs):
        if recursive:
            return [{'demo': 'value'}]
        return 'value'

    def list(self, dataset_type, header, *args, **kwargs):
        if header:
            return 'TABLE'
        return [['-', 'demo', 'down', '15.1-RELEASE', 'DHCP']]

    def snap_list(self, *args, **kwargs):
        return [['snap', 'created', '1K', '2K']]


@pytest.fixture
def load_cli(monkeypatch):
    messages = []

    common = types.ModuleType('iocage_lib.ioc_common')
    common.checkoutput = lambda *args, **kwargs: '15.0-RELEASE'
    common.ioc_sort = lambda *args, **kwargs: lambda row: row[0]
    common.logit = lambda data: messages.append(data['message'])

    iocage = types.ModuleType('iocage_lib.iocage')
    iocage.CLICK_WORKAROUND = True
    iocage.IOCage = FakeIOCage

    plugin = types.ModuleType('iocage_lib.ioc_plugin')
    plugin.reject_remote_plugin_operation = lambda: None

    package = types.ModuleType('iocage_lib')
    package.__path__ = []
    package.ioc_common = common
    package.iocage = iocage
    package.ioc_plugin = plugin

    texttable = types.ModuleType('texttable')
    texttable.Texttable = FakeTexttable

    monkeypatch.setitem(sys.modules, 'iocage_lib', package)
    monkeypatch.setitem(sys.modules, 'iocage_lib.ioc_common', common)
    monkeypatch.setitem(sys.modules, 'iocage_lib.iocage', iocage)
    monkeypatch.setitem(sys.modules, 'iocage_lib.ioc_plugin', plugin)
    monkeypatch.setitem(sys.modules, 'texttable', texttable)

    def load(command):
        path = Path(__file__).parents[2] / 'iocage_cli' / f'{command}.py'
        spec = importlib.util.spec_from_file_location(
            f'_header_flag_test_{command}', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.cli, messages

    FakeIOCage.calls = []
    return load


@pytest.mark.parametrize('command,default_args,flag_args,machine_line', [
    ('list', [], ['-H'], '-\tdemo\tdown\t15.1-RELEASE\tDHCP'),
    ('df', [], ['-H'], 'demo\t1.00x\tnone\tnone\t1G\t2G'),
    ('get', ['-r', 'property'], ['-H', '-r', 'property'], 'demo\tvalue'),
    (
        'fstab', ['-l', 'demo'], ['-H', '-l', 'demo'],
        '0\tsource\tdestination\tnullfs\tro\t0\t0',
    ),
    ('snaplist', ['demo'], ['-H', 'demo'], 'snap\tcreated\t1K\t2K'),
])
def test_header_flag_selects_machine_output(
    load_cli, command, default_args, flag_args, machine_line
):
    cli, messages = load_cli(command)
    runner = CliRunner()

    default_result = runner.invoke(cli, default_args)

    assert default_result.exit_code == 0, default_result.exception
    assert messages == ['TABLE']

    messages.clear()
    flag_result = runner.invoke(cli, flag_args)

    assert flag_result.exit_code == 0, flag_result.exception
    assert messages == [machine_line]


def test_list_header_output_remains_usable_by_zsh_completion(load_cli):
    cli, messages = load_cli('list')

    result = CliRunner().invoke(cli, ['-H'])

    assert result.exit_code == 0, result.exception
    assert [line.split('\t')[1] for line in messages] == ['demo']


def test_list_http_flag_preserves_default_true_behavior(load_cli):
    cli, messages = load_cli('list')
    runner = CliRunner()

    default_result = runner.invoke(cli, ['-R'])
    explicit_result = runner.invoke(cli, ['-R', '--http'])

    assert default_result.exit_code == 0, default_result.exception
    assert explicit_result.exit_code == 0, explicit_result.exception
    assert [call[1]['http'] for call in FakeIOCage.calls] == [True, False]
