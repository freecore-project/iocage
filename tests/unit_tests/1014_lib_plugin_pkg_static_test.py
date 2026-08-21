import iocage_lib.ioc_plugin as ioc_plugin


def test_package_removal_uses_jail_static_pkg(monkeypatch):
    captured = {}

    class FakeExec:
        def __init__(self, command, path, **kwargs):
            captured.update({
                'command': command,
                'path': path,
                'kwargs': kwargs,
            })

        def __enter__(self):
            return ()

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(ioc_plugin.iocage_lib.ioc_exec, 'IOCExec', FakeExec)
    monkeypatch.setattr(
        ioc_plugin.iocage_lib.ioc_common,
        'consume_and_log',
        lambda *args, **kwargs: None,
    )

    plugin = object.__new__(ioc_plugin.IOCPlugin)
    plugin.iocroot = '/iocage'
    plugin.jail = 'example_plugin'
    plugin.callback = None
    plugin.silent = True

    plugin.__update_pkg_remove__('42')

    assert captured == {
        'command': [
            '/usr/local/sbin/pkg-static',
            'delete', '-a', '-f', '-y',
        ],
        'path': '/iocage/jails/example_plugin',
        'kwargs': {
            'uuid': 'example_plugin',
            'callback': None,
        },
    }
