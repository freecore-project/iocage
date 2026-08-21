# Copyright (c) 2014-2019, iocage
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
"""iocage exec module."""
import collections
import errno
import fcntl
import os
import pty
import re
import resource
import select
import signal
import struct
import subprocess as su
import termios
import tty

import iocage_lib.ioc_common
import iocage_lib.ioc_json
import iocage_lib.ioc_list
import iocage_lib.ioc_start
import iocage_lib.ioc_exceptions


_WINSIZE = struct.Struct('HHHH')


def _copy_terminal_size(source_fd, target_fd):
    """Copy a terminal size without exposing the source terminal."""
    try:
        size = fcntl.ioctl(
            source_fd, termios.TIOCGWINSZ, _WINSIZE.pack(0, 0, 0, 0)
        )
        fcntl.ioctl(target_fd, termios.TIOCSWINSZ, size)
    except (OSError, termios.error):
        return False

    return True


def _close_inherited_fds():
    """Leave the isolated child only its pseudo-terminal descriptors."""
    maximum = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    if maximum == resource.RLIM_INFINITY:
        try:
            maximum = os.sysconf('SC_OPEN_MAX')
        except (OSError, ValueError):
            maximum = 65536
    os.closerange(3, int(maximum))


def _restore_exec_signals():
    """Match subprocess' default signal restoration before exec."""
    for name in ('SIGPIPE', 'SIGXFZ', 'SIGXFSZ'):
        signum = getattr(signal, name, None)
        if signum is not None:
            signal.signal(signum, signal.SIG_DFL)


def _write_all(fd, data):
    while data:
        try:
            written = os.write(fd, data)
        except InterruptedError:
            continue
        data = data[written:]


def _wait_for_child(pid):
    while True:
        try:
            _, status = os.waitpid(pid, 0)
        except InterruptedError:
            continue
        return os.waitstatus_to_exitcode(status)


def _signal_child(pid, signum):
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            pass


def _is_terminal(fd):
    try:
        return os.isatty(fd)
    except OSError:
        return False


def _hold_descriptors(descriptors):
    """Copy host descriptors above 2 before the child's 0-2 are replaced."""
    return {
        target: fcntl.fcntl(fd, fcntl.F_DUPFD, 3)
        for target, fd in descriptors.items()
    }


def _place_descriptors(held):
    for target, fd in held.items():
        os.dup2(fd, target)
        os.close(fd)


def _install_signal_handlers(handlers):
    previous = {}
    for signum, handler in handlers:
        if signum is None:
            continue
        try:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, handler)
        except ValueError:
            # Signal handlers are main-thread only. This keeps the relay
            # usable by embedded library callers while the CLI gets full
            # resize and interrupt handling.
            previous.pop(signum, None)
    return previous


def _exec_child(command, env, setup):
    """Finish the forked child: descriptors, signals, then exec."""
    try:
        setup()
        _close_inherited_fds()
        _restore_exec_signals()
        os.execvpe(command[0], command, env)
    except BaseException as e:
        message = f'iocage: failed to execute {command[0]}: {e}\n'
        with iocage_lib.ioc_exceptions.ignore_exceptions(OSError):
            os.write(2, message.encode(errors='replace'))
        os._exit(127)


def _run_in_new_session(command, env, host_fds):
    """
    Run an argv in a new session with the host descriptors passed through.

    Used when none of the descriptors is a terminal: output stays byte-exact,
    stderr stays separate and stdin EOF is a real EOF. The new session has no
    controlling terminal, so the child cannot reach the terminal of the shell
    that started iocage.
    """
    pid = os.fork()

    if pid == 0:
        def setup():
            os.setsid()
            _place_descriptors(_hold_descriptors(host_fds))

        _exec_child(command, env, setup)

    def forward_signal(signum, _frame):
        _signal_child(pid, signum)

    signal_handlers = _install_signal_handlers(
        (signum, forward_signal)
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    )
    try:
        return _wait_for_child(pid)
    finally:
        for signum, handler in signal_handlers.items():
            signal.signal(signum, handler)


def _run_isolated_pty(command, env, stdin_fd=0, stdout_fd=1, stderr_fd=2):
    """
    Run an interactive argv isolated from the host terminal.

    Host descriptors that are terminals are replaced by a new controlling
    pseudo-terminal: only bytes, terminal size, and approved environment
    values cross that boundary, and the child never receives the host
    terminal descriptor, so a jail process cannot use terminal ioctls
    against the host root shell. Pipes and files are passed through
    unchanged, so redirected and piped output stays byte-exact.
    """
    if isinstance(command, (str, bytes)) or not command:
        raise ValueError('Interactive command must be a non-empty argv')

    command = list(command)
    child_env = dict(env)
    host_fds = {0: stdin_fd, 1: stdout_fd, 2: stderr_fd}
    terminals = {n for n, fd in host_fds.items() if _is_terminal(fd)}
    if not terminals:
        return _run_in_new_session(command, child_env, host_fds)

    passed = {n: fd for n, fd in host_fds.items() if n not in terminals}
    relay_input = 0 in terminals
    size_fd = host_fds[min(terminals)]
    # Output from the pseudo-terminal goes back to a host terminal: stdout or
    # stderr, else the stdin terminal (prompts written to /dev/tty).
    output_fd = next(host_fds[n] for n in (1, 2, 0) if n in terminals)
    output_on_stdin = output_fd == stdin_fd and relay_input
    master_fd, slave_fd = pty.openpty()
    _copy_terminal_size(size_fd, slave_fd)
    pid = os.fork()

    if pid == 0:
        def setup():
            os.close(master_fd)
            held = _hold_descriptors(passed)
            if hasattr(os, 'login_tty'):
                os.login_tty(slave_fd)
            else:
                os.setsid()
                fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                for fd in (0, 1, 2):
                    os.dup2(slave_fd, fd)
                if slave_fd > 2:
                    os.close(slave_fd)
            _place_descriptors(held)

        _exec_child(command, child_env, setup)

    os.close(slave_fd)
    original_mode = None
    relay_error = None
    signal_handlers = {}

    try:
        if relay_input:
            try:
                original_mode = termios.tcgetattr(stdin_fd)
                tty.setraw(stdin_fd)
            except (OSError, termios.error):
                pass

        def resize_terminal(_signum=None, _frame=None):
            _copy_terminal_size(size_fd, master_fd)

        def forward_signal(signum, _frame):
            _signal_child(pid, signum)

        signal_handlers = _install_signal_handlers((
            (getattr(signal, 'SIGWINCH', None), resize_terminal),
            (signal.SIGINT, forward_signal),
        ))

        input_open = relay_input
        while True:
            readers = [master_fd]
            if input_open:
                readers.append(stdin_fd)

            try:
                ready, _, _ = select.select(readers, [], [])
            except InterruptedError:
                continue

            if master_fd in ready:
                try:
                    output = os.read(master_fd, 65536)
                except OSError as e:
                    if e.errno == errno.EIO:
                        break
                    raise
                if not output:
                    break
                if output_fd is not None:
                    try:
                        _write_all(output_fd, output)
                    except OSError as e:
                        # A stdin terminal opened read-only cannot show it.
                        if not output_on_stdin or e.errno != errno.EBADF:
                            raise
                        output_fd = None

            if input_open and stdin_fd in ready:
                data = os.read(stdin_fd, 65536)
                if data:
                    _write_all(master_fd, data)
                else:
                    # A host terminal hanging up must become terminal EOF.
                    _write_all(master_fd, b'\x04')
                    input_open = False
    except BaseException as e:
        relay_error = e
        _signal_child(pid, signal.SIGHUP)
    finally:
        for signum, handler in signal_handlers.items():
            signal.signal(signum, handler)
        if original_mode is not None:
            with iocage_lib.ioc_exceptions.ignore_exceptions(
                OSError, termios.error
            ):
                termios.tcsetattr(
                    stdin_fd, termios.TCSAFLUSH, original_mode
                )
        with iocage_lib.ioc_exceptions.ignore_exceptions(OSError):
            os.close(master_fd)

    returncode = _wait_for_child(pid)
    if relay_error is not None:
        raise relay_error
    return returncode


class IOCExec(object):
    """Run jexec with a user inside the specified jail."""
    def __init__(
        self,
        command,
        path,
        # None is special for RELEASE updating to work around
        # freebsd-update weirdness
        uuid='',
        host_user='root',
        jail_user=None,
        plugin=False,
        unjailed=False,
        skip=False,
        stdin_bytestring=None,
        su_env=None,
        keep_proxy=False,
        decode=False,
        callback=None
    ):
        self.command = command
        self.uuid = uuid.replace(".", "_") if uuid is not None else uuid
        self.path = path
        self.host_user = host_user
        self.jail_user = jail_user
        self.plugin = plugin
        self.unjailed = unjailed
        self.skip = skip
        self.stdin_bytestring = stdin_bytestring
        self.decode = decode
        self.stdin = su.PIPE if self.stdin_bytestring is not None else None

        path = '/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/sbin:'\
               '/usr/local/bin:/root/bin'
        env_lang = os.environ.get('LANG', 'en_US.UTF-8')
        su_env = su_env or {}
        su_env.setdefault('PATH', path)
        su_env.setdefault('PWD', '/')
        su_env.setdefault('HOME', '/')
        su_env.setdefault('TERM', 'xterm-256color')
        su_env.setdefault('LANG', env_lang)
        su_env.setdefault('LC_ALL', env_lang)
        if unjailed or keep_proxy:
            if os.environ.get('http_proxy', '') != '':
                su_env.setdefault('http_proxy', os.environ.get('http_proxy', ''))
            elif os.environ.get('HTTP_PROXY', '') != '':
                su_env.setdefault('HTTP_PROXY', os.environ.get('HTTP_PROXY', ''))
            if os.environ.get('HTTPS_PROXY', '') != '':
                su_env.setdefault('HTTPS_PROXY', os.environ.get('HTTPS_PROXY', ''))
            if os.environ.get('HTTP_PROXY_AUTH', '') != '':
                su_env.setdefault('HTTP_PROXY_AUTH', os.environ.get('HTTP_PROXY_AUTH', ''))
            if os.environ.get('NO_PROXY', '') != '':
                su_env.setdefault('NO_PROXY', os.environ.get('NO_PROXY', ''))

        self.su_env = su_env
        self.callback = callback
        self.cmd = self.command

        if self.uuid is not None and self.uuid:
            self.status, _ = iocage_lib.ioc_list.IOCList().list_get_jid(
                self.uuid)
            self.conf = iocage_lib.ioc_json.IOCJson(self.path).json_get_value(
                'all')
            exec_fib = self.conf["exec_fib"]

            self.flight_checks()

            if not self.unjailed:
                if self.jail_user:
                    flag = "-U"
                    user = self.jail_user
                else:
                    flag = "-u"
                    user = self.host_user

                self.cmd = [
                    '/usr/sbin/setfib', exec_fib, 'jexec', flag, user,
                    f'ioc-{self.uuid.replace(".", "_")}'
                ] + list(self.command)

    def __enter__(self):
        self.proc = su.Popen(
            self.cmd, stdout=su.PIPE, stderr=su.PIPE, stdin=self.stdin,
            close_fds=True, bufsize=0, env=self.su_env
        )

        if self.stdin is not None:
            self.proc.stdin.write(self.stdin_bytestring)

        self.exec_gen = self.exec_jail()

        return self.exec_gen

    def __exit__(self, *args):
        try:
            for i in self.exec_gen:
                continue
        except StopIteration:
            pass

        try:
            self.proc.wait(timeout=15)

            self.proc.stdout.close()
            self.proc.stderr.close()

            if self.stdin is not None:
                self.proc.stdin.close()
        except su.TimeoutExpired:
            self.proc.kill()

            self.proc.stdout.close()
            self.proc.stderr.close()

            if self.stdin is not None:
                self.proc.stdin.close()

    def flight_checks(self):
        if not self.status:
            if not self.plugin and not self.skip:
                iocage_lib.ioc_common.logit(
                    {
                        "level": "INFO",
                        "message": f"{self.uuid} is not running,"
                        " starting jail"
                    },
                    _callback=self.callback)

            if self.conf["type"] in (
                    "jail", "plugin", "pluginv2", "clonejail"):
                iocage_lib.ioc_start.IOCStart(self.uuid, self.path,
                                              silent=True)
                self.status = True
            elif self.conf["type"] == "basejail":
                iocage_lib.ioc_common.logit(
                    {
                        "level":
                        "EXCEPTION",
                        "message":
                        "Please run \"iocage migrate\" before trying"
                        f" to start {self.uuid}"
                    },
                    _callback=self.callback)
            elif self.conf["type"] == "template":
                iocage_lib.ioc_common.logit(
                    {
                        "level":
                        "EXCEPTION",
                        "message":
                        "Please convert back to a jail before trying"
                        f" to start {self.uuid}"
                    },
                    _callback=self.callback)
            else:
                iocage_lib.ioc_common.logit(
                    {
                        "level":
                        "EXCEPTION",
                        "message":
                        f"{self.conf['type']} is not a supported jail type."
                    },
                    _callback=self.callback)

            if not self.skip:
                iocage_lib.ioc_common.logit(
                    {
                        "level": "INFO",
                        "message": "\nCommand output:"
                    },
                    _callback=self.callback)

    def exec_jail(self):
        # Courtesy of @william-gr
        # service(8) and some rc.d scripts have the bad habit of
        # exec'ing and never closing stdout/stderr. This makes
        # sure we read only enough until the command exits and do
        # not wait on the pipe to close on the other end.
        #
        # Same issue can be demonstrated with:
        # $ jexec 1 service postgresql onerestart | cat
        # ... <hangs>
        # postgresql rc.d command never closes the pipe
        stderr_queue = collections.deque(maxlen=30)
        rtrn_stdout = _rtrn_stdout = rtrn_stderr = b''

        for i in ('stdout', 'stderr'):
            fileno = getattr(self.proc, i).fileno()
            fl = fcntl.fcntl(fileno, fcntl.F_GETFL)
            fcntl.fcntl(fileno, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        timeout = 0.1

        while True:
            r = select.select([
                self.proc.stdout.fileno(),
                self.proc.stderr.fileno()], [], [], timeout)[0]

            if self.proc.poll() is not None:
                if timeout == 0:
                    break
                else:
                    timeout = 0

            if r:
                if self.proc.stdout.fileno() in r:
                    rtrn_stdout = self.proc.stdout.read()

                    if rtrn_stdout:
                        _rtrn_stdout = rtrn_stdout
                if self.proc.stderr.fileno() in r:
                    rtrn_stderr = self.proc.stderr.read()
                    stderr_queue.append(rtrn_stderr)

                if not self.decode:
                    yield rtrn_stdout, rtrn_stderr
                else:
                    yield rtrn_stdout.decode(), rtrn_stderr.decode()

        error = True if self.proc.returncode != 0 else False

        # self.uuid being None means a RELEASE being updated,
        # We will get false positives for EOL notices
        if error and self.uuid is not None:
            # EOL notice for jail updates
            jail_eol_regex = \
                rb'(WARNING: FreeBSD \d*\.\d-RELEASE HAS PASSED ITS'\
                rb' END-OF-LIFE DATE)'

            if re.search(jail_eol_regex, _rtrn_stdout):
                error = False

            if error:
                raise iocage_lib.ioc_exceptions.CommandFailed(
                    list(stderr_queue)
                )


class SilentExec(object):
    def __init__(self, *args, **kwargs):
        decode = kwargs.get('decode', False)
        with IOCExec(*args, **kwargs) as silent:  # noqa
            self.output = list(silent)

        join_str = b'' if not decode else ''
        self.stdout = join_str.join([i[0] for i in self.output])
        self.stderr = join_str.join([i[1] for i in self.output])


class InteractiveExec(IOCExec):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.unjailed:
            if not self.uuid or self.uuid is None:
                iocage_lib.ioc_common.logit(
                    {
                        'level': 'EXCEPTION',
                        'message': 'UUID is required'
                    },
                    exception=iocage_lib.ioc_exceptions.ValueNotFound,
                    _callback=self.callback)

            if not self.path or self.path is None:
                iocage_lib.ioc_common.logit(
                    {
                        'level': 'EXCEPTION',
                        'message': 'Path is required'
                    },
                    exception=iocage_lib.ioc_exceptions.ValueNotFound,
                    _callback=self.callback)

            if not self.status:
                iocage_lib.ioc_start.IOCStart(
                    self.uuid, self.path, silent=True
                )
                self.status, _ = iocage_lib.ioc_list.IOClist(
                    'jid', uuid=self.uuid
                )

        returncode = _run_isolated_pty(self.cmd, self.su_env)
        if returncode:
            iocage_lib.ioc_common.logit(
                {
                    'level': 'EXCEPTION',
                    'message': f'Command: {" ".join(self.command)} failed!'
                },
                exception=iocage_lib.ioc_exceptions.CommandFailed,
                _callback=self.callback)
