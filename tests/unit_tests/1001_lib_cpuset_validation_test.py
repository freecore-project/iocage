from unittest.mock import Mock, patch

import pytest

from iocage_lib.ioc_exceptions import CommandFailed
from iocage_lib.ioc_json import IOCCpuset, IOCRCTL

# For cpuset props we would like to test the following scenarios
# 1) 0,1,2,3
# 2) 0-3
# 3) all
# 4) off


# Tests for point 1
def test_01_full_range():
    with patch(
        'iocage_lib.ioc_json.IOCCpuset.retrieve_cpu_sets',
        Mock(return_value=6)
    ):
        assert IOCCpuset.validate_cpuset_prop('0,1,2,3,4,5', False) is False


def test_02_subset_of_complete_range():
    with patch(
        'iocage_lib.ioc_json.IOCCpuset.retrieve_cpu_sets',
        Mock(return_value=6)
    ):
        assert IOCCpuset.validate_cpuset_prop('1,2,3', False) is False


def test_03_order_is_irrelevant():
    with patch(
        'iocage_lib.ioc_json.IOCCpuset.retrieve_cpu_sets',
        Mock(return_value=60)
    ):
        assert IOCCpuset.validate_cpuset_prop('2,1,4,11', False) is False


def test_04_duplicates_are_not_allowed():
    with patch(
        'iocage_lib.ioc_json.IOCCpuset.retrieve_cpu_sets',
        Mock(return_value=60)
    ):
        assert IOCCpuset.validate_cpuset_prop('1,2,1', False) is True


def test_05_order_for_commas_to_be_respected():
    with patch(
        'iocage_lib.ioc_json.IOCCpuset.retrieve_cpu_sets',
        Mock(return_value=60)
    ):
        assert IOCCpuset.validate_cpuset_prop('1,2,', False) is True
        assert IOCCpuset.validate_cpuset_prop(',1,2', False) is True


def test_06_invalid_cpuset_value_not_allowed():
    with patch(
        'iocage_lib.ioc_json.IOCCpuset.retrieve_cpu_sets',
        Mock(return_value=60)
    ):
        assert IOCCpuset.validate_cpuset_prop('1,2,99', False) is True


def test_07_cpuset_value_not_retrieved():
    with patch(
        'iocage_lib.ioc_json.IOCCpuset.retrieve_cpu_sets',
        Mock(return_value=-2)
    ):
        assert IOCCpuset.validate_cpuset_prop('1,2,99', False) is True


def test_08_single_cpuset_value():
    with patch(
        'iocage_lib.ioc_json.IOCCpuset.retrieve_cpu_sets',
        Mock(return_value=0)
    ):
        assert IOCCpuset.validate_cpuset_prop('0', False) is False


# Tests for point 2
def test_09_valid_range():
    with patch(
        'iocage_lib.ioc_json.IOCCpuset.retrieve_cpu_sets',
        Mock(return_value=60)
    ):
        assert IOCCpuset.validate_cpuset_prop('0-59', False) is False


def test_10_invalid_range_not_allowed():
    with patch(
        'iocage_lib.ioc_json.IOCCpuset.retrieve_cpu_sets',
        Mock(return_value=60)
    ):
        assert IOCCpuset.validate_cpuset_prop('0-99', False) is True


def test_11_subset_of_cpus_in_range():
    with patch(
        'iocage_lib.ioc_json.IOCCpuset.retrieve_cpu_sets',
        Mock(return_value=60)
    ):
        assert IOCCpuset.validate_cpuset_prop('12-22', False) is False


# Tests for point 3 and 4
def test_12_off_value():
    with patch.object(IOCCpuset, 'retrieve_cpu_sets', return_value=15):
        assert IOCCpuset.validate_cpuset_prop('off', False) is False


def test_13_all_value():
    with patch.object(IOCCpuset, 'retrieve_cpu_sets', return_value=15):
        assert IOCCpuset.validate_cpuset_prop('all', False) is False


def test_14_invalid_value_not_allowed():
    with patch.object(IOCCpuset, 'retrieve_cpu_sets', return_value=15):
        assert IOCCpuset.validate_cpuset_prop('gibberish', False) is True


def test_set_cpuset_returns_failure_for_expected_command_error():
    with patch(
        'iocage_lib.ioc_exec.SilentExec',
        side_effect=CommandFailed('cpuset failed'),
    ):
        assert IOCCpuset('test').set_cpuset('0-3') is True


def test_set_cpuset_does_not_suppress_unexpected_exception():
    with patch(
        'iocage_lib.ioc_exec.SilentExec',
        side_effect=RuntimeError('unexpected cpuset error'),
    ), pytest.raises(RuntimeError, match='unexpected cpuset error'):
        IOCCpuset('test').set_cpuset('0-3')


def test_retrieve_cpu_sets_parses_freebsd_15_output():
    output = Mock(stdout=(
        'cpuset 0 mask: 0, 1, 2, 3, 4, 5, 6, 7, '
        '8, 9, 10, 11, 12, 13, 14, 15\n'
    ))
    with patch(
        'iocage_lib.ioc_exec.SilentExec', return_value=output
    ) as execute:
        assert IOCCpuset.retrieve_cpu_sets() == 15

    execute.assert_called_once_with(
        ['cpuset', '-g', '-s', '0'],
        None, unjailed=True, decode=True
    )


def test_retrieve_cpu_sets_returns_fallback_for_expected_command_error():
    with patch(
        'iocage_lib.ioc_exec.SilentExec',
        side_effect=CommandFailed('cpuset failed'),
    ):
        assert IOCCpuset.retrieve_cpu_sets() == -2


def test_retrieve_cpu_sets_does_not_suppress_unexpected_exception():
    with patch(
        'iocage_lib.ioc_exec.SilentExec',
        side_effect=RuntimeError('unexpected cpuset query error'),
    ), pytest.raises(RuntimeError, match='unexpected cpuset query error'):
        IOCCpuset.retrieve_cpu_sets()


def test_rctl_rules_exist_matches_requested_rule():
    output = Mock(stdout=(
        'jail:ioc-test:memoryuse:deny=1G\n'
        'jail:ioc-other:maxproc:deny=100\n'
    ))
    with patch('iocage_lib.ioc_exec.SilentExec', return_value=output):
        assert IOCRCTL('test').rctl_rules_exist('memoryuse') is True
        assert IOCRCTL('test').rctl_rules_exist('maxproc') is False


def test_rctl_rules_exist_returns_fallback_for_expected_command_error():
    with patch(
        'iocage_lib.ioc_exec.SilentExec',
        side_effect=CommandFailed('rctl failed'),
    ):
        assert IOCRCTL('test').rctl_rules_exist() is False


def test_rctl_rules_exist_does_not_suppress_unexpected_exception():
    with patch(
        'iocage_lib.ioc_exec.SilentExec',
        side_effect=RuntimeError('unexpected rctl error'),
    ), pytest.raises(RuntimeError, match='unexpected rctl error'):
        IOCRCTL('test').rctl_rules_exist()
