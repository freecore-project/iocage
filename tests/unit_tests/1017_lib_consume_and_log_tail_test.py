# the internal development record: consume_and_log keeps a last line that has no
# trailing newline.
from iocage_lib.ioc_common import consume_and_log


def consume(chunks):
    return consume_and_log(iter(chunks), log=False)


def test_01_complete_lines_unchanged():
    out = consume([(b'a\nb\n', b''), (b'c\n', b'')])
    assert out == {'stdout': ['a\nb\n', 'c\n'], 'stderr': []}


def test_02_last_line_without_newline_is_kept():
    assert consume([(b'hello', b'')])['stdout'] == ['hello']


def test_03_tail_after_complete_lines():
    out = consume([(b'1\n2\n', b''), (b'3', b'')])
    assert ''.join(out['stdout']) == '1\n2\n3'


def test_04_line_split_across_chunks():
    out = consume([(b'ab', b''), (b'c\nd', b'')])
    assert ''.join(out['stdout']) == 'abc\nd'


def test_05_stderr_tail_is_kept():
    out = consume([(b'out\n', b'err')])
    assert out == {'stdout': ['out\n'], 'stderr': ['err']}


def test_06_no_output():
    assert consume([]) == {'stdout': [], 'stderr': []}
