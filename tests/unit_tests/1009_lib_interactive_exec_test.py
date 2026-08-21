import fcntl
import json
import os
import pty
import signal
import struct
import sys
import termios
import threading
import time
from unittest import mock

import pytest

import iocage_lib.ioc_common as ioc_common
import iocage_lib.ioc_exceptions as ioc_exceptions
import iocage_lib.ioc_exec as ioc_exec


WINSIZE = struct.Struct('HHHH')


def _child_env():
    return {
        'PATH': os.environ['PATH'],
        'TERM': 'xterm-256color',
        'LANG': 'C',
        'LC_ALL': 'C',
    }


def _read_all(fd):
    chunks = []
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            return b''.join(chunks)
        chunks.append(chunk)


def _json_from_pty(output):
    for line in output.decode(errors='replace').splitlines():
        start = line.find('{')
        end = line.rfind('}')
        if start >= 0 and end > start:
            return json.loads(line[start:end + 1])
    raise AssertionError(f'No JSON object in PTY output: {output!r}')


def test_child_gets_distinct_tty_and_no_host_terminal_descriptor():
    host_master, host_slave = pty.openpty()
    output_read, output_write = os.pipe()
    host_tty = os.ttyname(host_slave)
    original_mode = termios.tcgetattr(host_slave)
    fcntl.ioctl(
        host_slave,
        termios.TIOCSWINSZ,
        WINSIZE.pack(33, 120, 0, 0),
    )
    script = r'''
import fcntl
import json
import os
import struct
import sys
import termios

host_fd = int(sys.argv[1])
try:
    os.fstat(host_fd)
except OSError:
    host_fd_open = False
else:
    host_fd_open = True

injection = 'unsupported'
if hasattr(termios, 'TIOCSTI'):
    try:
        fcntl.ioctl(0, termios.TIOCSTI, b'X')
    except OSError as e:
        injection = f'blocked:{e.errno}'
    else:
        injection = 'isolated'

rows, columns, _, _ = struct.unpack(
    'HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ, bytes(8))
)
print(json.dumps({
    'tty': os.ttyname(0),
    'host_fd_open': host_fd_open,
    'injection': injection,
    'rows': rows,
    'columns': columns,
}), flush=True)
'''

    try:
        status = ioc_exec._run_isolated_pty(
            [sys.executable, '-c', script, str(host_slave)],
            _child_env(),
            host_slave,
            output_write,
        )
        os.close(output_write)
        output_write = None
        report = _json_from_pty(_read_all(output_read))

        assert status == 0
        assert report['tty'] != host_tty
        assert report['host_fd_open'] is False
        assert report['injection'] == 'isolated' or \
            report['injection'].startswith('blocked:')
        assert (report['rows'], report['columns']) == (33, 120)
        assert termios.tcgetattr(host_slave) == original_mode

        pending = fcntl.ioctl(
            host_slave, termios.FIONREAD, struct.pack('I', 0)
        )
        assert struct.unpack('I', pending)[0] == 0
    finally:
        if output_write is not None:
            os.close(output_write)
        os.close(output_read)
        os.close(host_slave)
        os.close(host_master)


def test_pipe_eof_reaches_child_and_exit_status_is_preserved():
    input_read, input_write = os.pipe()
    output_read, output_write = os.pipe()
    os.write(input_write, b'payload\n')
    os.close(input_write)
    script = (
        'import json, sys; '
        'print(json.dumps({"input": sys.stdin.read()}), flush=True); '
        'raise SystemExit(23)'
    )

    try:
        status = ioc_exec._run_isolated_pty(
            [sys.executable, '-c', script],
            _child_env(),
            input_read,
            output_write,
        )
        os.close(output_write)
        output_write = None
        report = _json_from_pty(_read_all(output_read))

        assert status == 23
        assert report == {'input': 'payload\n'}
    finally:
        os.close(input_read)
        if output_write is not None:
            os.close(output_write)
        os.close(output_read)


def test_ctrl_c_is_delivered_to_isolated_foreground_process(tmp_path):
    host_master, host_slave = pty.openpty()
    output_read, output_write = os.pipe()
    ready = tmp_path / 'interrupt-ready'
    worker_error = []
    script = r'''
import pathlib
import signal
import sys

def interrupted(_signum, _frame):
    print('INTERRUPTED', flush=True)
    raise SystemExit(42)

signal.signal(signal.SIGINT, interrupted)
pathlib.Path(sys.argv[1]).touch()
signal.pause()
'''

    def send_interrupt():
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not ready.exists():
            worker_error.append('child did not become ready')
        os.write(host_master, b'\x03')

    worker = threading.Thread(target=send_interrupt)
    worker.start()
    try:
        status = ioc_exec._run_isolated_pty(
            [sys.executable, '-c', script, str(ready)],
            _child_env(),
            host_slave,
            output_write,
        )
        os.close(output_write)
        output_write = None
        output = _read_all(output_read)
    finally:
        worker.join(timeout=5)
        if output_write is not None:
            os.close(output_write)
        os.close(output_read)
        os.close(host_slave)
        os.close(host_master)

    assert not worker_error
    assert not worker.is_alive()
    assert status == 42
    assert b'INTERRUPTED' in output


@pytest.mark.skipif(
    not hasattr(signal, 'SIGWINCH'), reason='SIGWINCH is unavailable'
)
def test_sigwinch_copies_resized_host_terminal_to_child(tmp_path):
    host_master, host_slave = pty.openpty()
    output_read, output_write = os.pipe()
    ready = tmp_path / 'resize-ready'
    worker_error = []
    fcntl.ioctl(
        host_slave,
        termios.TIOCSWINSZ,
        WINSIZE.pack(24, 80, 0, 0),
    )
    script = r'''
import fcntl
import json
import pathlib
import signal
import struct
import sys
import termios

def resized(_signum, _frame):
    rows, columns, _, _ = struct.unpack(
        'HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ, bytes(8))
    )
    print(json.dumps({'rows': rows, 'columns': columns}), flush=True)
    raise SystemExit(0)

signal.signal(signal.SIGWINCH, resized)
pathlib.Path(sys.argv[1]).touch()
signal.pause()
'''

    def resize_host():
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not ready.exists():
            worker_error.append('child did not become ready')
        fcntl.ioctl(
            host_slave,
            termios.TIOCSWINSZ,
            WINSIZE.pack(50, 160, 0, 0),
        )
        os.kill(os.getpid(), signal.SIGWINCH)

    worker = threading.Thread(target=resize_host)
    worker.start()
    try:
        status = ioc_exec._run_isolated_pty(
            [sys.executable, '-c', script, str(ready)],
            _child_env(),
            host_slave,
            output_write,
        )
        os.close(output_write)
        output_write = None
        report = _json_from_pty(_read_all(output_read))
    finally:
        worker.join(timeout=5)
        if output_write is not None:
            os.close(output_write)
        os.close(output_read)
        os.close(host_slave)
        os.close(host_master)

    assert not worker_error
    assert not worker.is_alive()
    assert status == 0
    assert report == {'rows': 50, 'columns': 160}


def test_interactive_exec_passes_only_approved_environment():
    jail_list = mock.Mock()
    jail_list.list_get_jid.return_value = (True, '42')
    jail_config = mock.Mock()
    jail_config.json_get_value.return_value = {
        'exec_fib': '0',
        'type': 'jail',
    }
    command = ['/bin/echo', '; touch /host-must-not-run']
    host_env = {
        'LANG': 'C.UTF-8',
        'http_proxy': 'http://proxy.invalid',
        'HTTPS_PROXY': 'http://secure-proxy.invalid',
        'HTTP_PROXY_AUTH': 'approved-auth',
        'NO_PROXY': 'localhost',
        'UNRELATED_HOST_SECRET': 'must-not-cross',
    }

    with mock.patch.dict(os.environ, host_env, clear=True), \
            mock.patch.object(
                ioc_exec.iocage_lib.ioc_list, 'IOCList',
                return_value=jail_list,
            ), mock.patch.object(
                ioc_exec.iocage_lib.ioc_json, 'IOCJson',
                return_value=jail_config,
            ), mock.patch.object(
                ioc_exec, '_run_isolated_pty', return_value=0,
            ) as isolated:
        ioc_exec.InteractiveExec(
            command,
            '/iocage/jails/test',
            uuid='test',
        )

    argv, child_env = isolated.call_args.args
    assert argv == [
        '/usr/sbin/setfib', '0', 'jexec', '-u', 'root', 'ioc-test',
        *command,
    ]
    assert child_env['PATH'].startswith('/sbin:/bin:')
    assert child_env['HOME'] == '/'
    assert child_env['TERM'] == 'xterm-256color'
    assert child_env['LANG'] == 'C.UTF-8'
    assert 'UNRELATED_HOST_SECRET' not in child_env

    # 15.0 leg: this iocage has no keep_proxy (iocage 1.13's 6518661); host
    # proxy settings never cross into a jail.
    proxy_keys = {
        'http_proxy', 'HTTPS_PROXY', 'HTTP_PROXY_AUTH', 'NO_PROXY'
    }
    assert proxy_keys.isdisjoint(child_env)


def test_interactive_nonzero_exit_raises_command_failed():
    jail_list = mock.Mock()
    jail_list.list_get_jid.return_value = (True, '42')
    jail_config = mock.Mock()
    jail_config.json_get_value.return_value = {
        'exec_fib': '0',
        'type': 'jail',
    }

    with mock.patch.object(
        ioc_exec.iocage_lib.ioc_list, 'IOCList', return_value=jail_list,
    ), mock.patch.object(
        ioc_exec.iocage_lib.ioc_json, 'IOCJson', return_value=jail_config,
    ), mock.patch.object(
        ioc_exec, '_run_isolated_pty', return_value=17,
    ), mock.patch.object(ioc_common, 'INTERACTIVE', False):
        with pytest.raises(ioc_exceptions.CommandFailed):
            ioc_exec.InteractiveExec(
                ['/bin/false'], '/iocage/jails/test', uuid='test'
            )


def test_unjailed_interactive_exec_passes_only_approved_environment():
    # 15.0 leg: without iocage 1.13's proxy pass-through, an unjailed command
    # gets the same approved environment as before the isolation change; the
    # point here is that unrelated host variables still do not cross.
    host_env = {
        'LANG': 'C.UTF-8',
        'http_proxy': 'http://proxy.invalid',
        'UNRELATED_HOST_SECRET': 'must-not-cross',
    }

    with mock.patch.dict(os.environ, host_env, clear=True), \
            mock.patch.object(
                ioc_exec, '_run_isolated_pty', return_value=0,
            ) as isolated:
        ioc_exec.InteractiveExec(
            ['/usr/sbin/freebsd-update', 'install'],
            '',
            uuid=None,
            unjailed=True,
        )

    argv, child_env = isolated.call_args.args
    assert argv == ['/usr/sbin/freebsd-update', 'install']
    assert 'UNRELATED_HOST_SECRET' not in child_env
