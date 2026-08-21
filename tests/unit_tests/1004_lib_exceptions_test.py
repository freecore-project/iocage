# Copyright (c) 2014-2019, iocage
# All rights reserved.
import iocage_lib.ioc_exceptions as ioc_exceptions


def test_exception_with_msg_preserves_string():
    exc = ioc_exceptions.CommandFailed('failed')
    assert exc.message == 'failed'


def test_exception_with_msg_preserves_iterable():
    message = [b'line 1', b'line 2']
    exc = ioc_exceptions.CommandFailed(message)
    assert exc.message is message


def test_exception_with_msg_wraps_non_iterable():
    exc = ioc_exceptions.CommandFailed(1)
    assert exc.message == [1]
