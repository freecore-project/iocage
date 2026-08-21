import iocage_lib.ioc_start
import iocage_lib.ioc_stop


def test__allow_dying__disabled_on_freebsd_15(monkeypatch):
    monkeypatch.setattr(iocage_lib.ioc_start.os, "uname", lambda: ("", "", "15.1-PRERELEASE"))

    assert iocage_lib.ioc_start.allow_dying_supported() is False


def test__allow_dying__kept_before_freebsd_15(monkeypatch):
    monkeypatch.setattr(iocage_lib.ioc_start.os, "uname", lambda: ("", "", "14.3-RELEASE"))

    assert iocage_lib.ioc_start.allow_dying_supported() is True


def test__allow_dying__kept_when_host_release_cannot_be_parsed(monkeypatch):
    monkeypatch.setattr(iocage_lib.ioc_start.os, "uname", lambda: ("", "", "CURRENT"))

    assert iocage_lib.ioc_start.allow_dying_supported() is True


def test__deprecated_allow_dying_stderr_is_ignorable():
    stderr = "jail: the 'allow.dying' parameter and '-d' flag are deprecated and have no effect."

    assert iocage_lib.ioc_stop.ignorable_jail_remove_stderr(stderr) is True


def test__other_jail_remove_stderr_is_not_ignorable():
    assert iocage_lib.ioc_stop.ignorable_jail_remove_stderr("jail not found") is False
