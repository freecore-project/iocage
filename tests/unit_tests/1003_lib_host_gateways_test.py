import json
from unittest.mock import patch

import pytest

from iocage_lib.ioc_common import (
    get_host_gateways,
    parse_dhcp_address,
    retrieve_ip4_for_jail,
)


@pytest.mark.parametrize(
    'ifconfig_output, expected',
    [
        (b"""epair0b: flags=8863<UP,BROADCAST,RUNNING> metric 0 mtu 1500
            description: jail side interface
            inet6 fe80::1%epair0b prefixlen 64
            options=8<VLAN_MTU>
            inet 192.0.2.10 broadcast 192.0.2.255 netmask 0xffffff00
            groups: epair
        """, ('192.0.2.10', 24)),
        ("""epair1b: flags=8863<UP,BROADCAST,RUNNING> metric 0 mtu 1500
            inet 198.51.100.12 netmask 255.255.255.128
            status: active
        """, ('198.51.100.12', 25)),
    ],
)
def test_parse_dhcp_address_uses_inet_fields(ifconfig_output, expected):
    assert parse_dhcp_address(ifconfig_output) == expected


@pytest.mark.parametrize(
    'ifconfig_output',
    [
        'epair0b: flags=8863<UP,BROADCAST,RUNNING>\n',
        '    inet 192.0.2.10 broadcast 192.0.2.255\n',
        '    inet invalid netmask 0xffffff00\n',
        '    inet 192.0.2.10 netmask 255.0.255.0\n',
    ],
)
def test_parse_dhcp_address_rejects_malformed_output(ifconfig_output):
    with pytest.raises(ValueError):
        parse_dhcp_address(ifconfig_output)


@patch('iocage_lib.ioc_common.checkoutput')
def test_01_get_host_gateways(mock_checkoutput):
    mock_checkoutput.side_effect = [netstat_output]
    assert get_host_gateways() == \
        {'ipv4': {'gateway': '217.29.43.254', 'interface': 'inet0'},
         'ipv6': {'gateway': 'fe80::8%inet0', 'interface': 'inet0'}}
    mock_checkoutput.assert_called_once_with([
        'setfib', '0', 'netstat', '-r', '-n', '--libxo', 'json'
    ])


def route_output(route_table):
    return json.dumps({
        'statistics': {
            'route-information': {
                'route-table': route_table,
            },
        },
    })


@pytest.mark.parametrize(
    'route_table, expected',
    [
        ({
            'rt-family': [{
                'address-family': 'Internet',
                'rt-entry': [{
                    'destination': 'default',
                    'gateway': '192.0.2.1',
                    'interface-name': 'igb0',
                }],
            }],
        }, {
            'ipv4': {'gateway': '192.0.2.1', 'interface': 'igb0'},
            'ipv6': {'gateway': None, 'interface': None},
        }),
        ({
            'rt-family': {
                'address-family': 'Internet6',
                'rt-entry': {
                    'destination': 'default',
                    'gateway': 'fe80::1%igb1',
                    'interface-name': 'igb1',
                },
            },
        }, {
            'ipv4': {'gateway': None, 'interface': None},
            'ipv6': {'gateway': 'fe80::1%igb1', 'interface': 'igb1'},
        }),
        ({
            'rt-family': [{
                'address-family': 'Internet',
            }],
        }, {
            'ipv4': {'gateway': None, 'interface': None},
            'ipv6': {'gateway': None, 'interface': None},
        }),
        ({'rt-family': []}, {
            'ipv4': {'gateway': None, 'interface': None},
            'ipv6': {'gateway': None, 'interface': None},
        }),
    ],
)
def test_get_host_gateways_normalizes_libxo_shapes(route_table, expected):
    with patch('iocage_lib.ioc_common.checkoutput') as mock_checkoutput:
        mock_checkoutput.return_value = route_output(route_table)

        assert get_host_gateways(4) == expected

    mock_checkoutput.assert_called_once_with([
        'setfib', '4', 'netstat', '-r', '-n', '--libxo', 'json'
    ])


@patch('iocage_lib.ioc_common.os.geteuid', return_value=0)
@patch('iocage_lib.ioc_common.su.check_output')
def test_retrieve_ip4_for_jail_uses_shared_dhcp_parser(
    mock_check_output, _mock_geteuid
):
    mock_check_output.return_value = b"""\
epair1b: flags=8863<UP,BROADCAST,RUNNING> metric 0 mtu 1500
    description: jail side interface
    options=8<VLAN_MTU>
    inet 198.51.100.12 netmask 0xffffff00 broadcast 198.51.100.255
"""
    conf = {
        'dhcp': 1,
        'host_hostuuid': 'dhcp.jail',
        'interfaces': 'vnet1:bridge1',
    }

    assert retrieve_ip4_for_jail(conf, True) == {
        'short_ip4': 'DHCP',
        'full_ip4': 'epair1b|198.51.100.12',
    }
    mock_check_output.assert_called_once_with([
        'jexec', 'ioc-dhcp_jail', 'ifconfig', 'epair1b', 'inet'
    ])


netstat_output = (
    '{"statistics": {"route-information": {"route-table": {"rt-family": '
    '[{"address-family":"Internet", "rt-entry": [{"destination":"default",'
    '"gateway":"217.29.43.254","flags":"UGS", "flags_pretty": ["up",'
    '"gateway","static"],"interface-name":"inet0"}, {"destination":'
    '"10.5.0.0/16","gateway":"link#5","flags":"U", "flags_pretty": ["up"],'
    '"interface-name":"mgmt0"}, {"destination":"10.5.105.29","gateway":'
    '"link#5","flags":"UHS", "flags_pretty": ["up","host","static"],'
    '"interface-name":"lo0"}, {"destination":"127.0.0.1","gateway":"lo0",'
    '"flags":"UHS", "flags_pretty": ["up","host","static"],"interface-name":'
    '"lo0"}, {"destination":"217.29.42.0/23","gateway":"link#4","flags":"U", '
    '"flags_pretty": ["up"],"interface-name":"inet0"}, {"destination":'
    '"217.29.42.186","gateway":"link#4","flags":"UHS", "flags_pretty": ["up",'
    '"host","static"],"interface-name":"lo0"}]}, {"address-family":'
    '"Internet6", "rt-entry": [{"destination":"::/96","gateway":"::1",'
    '"flags":"UGRS", "flags_pretty": ["up","gateway","reject","static"],'
    '"interface-name":"lo0"}, {"destination":"default","gateway":'
    '"fe80::8%inet0","flags":"UGS", "flags_pretty": ["up","gateway","static"]'
    ',"interface-name":"inet0"}, {"destination":"::1","gateway":"lo0","flags"'
    ':"UHS", "flags_pretty": ["up","host","static"],"interface-name":"lo0"}, '
    '{"destination":"::ffff:0.0.0.0/96","gateway":"::1","flags":"UGRS", '
    '"flags_pretty": ["up","gateway","reject","static"],"interface-name":'
    '"lo0"}, {"destination":"2a00:b580:8000:8::/64","gateway":"link#4",'
    '"flags":"U", "flags_pretty": ["up"],"interface-name":"inet0"}, '
    '{"destination":"2a00:b580:8000:8:9d6:2f93:3504:d4c9","gateway":"link#4",'
    '"flags":"UHS", "flags_pretty": ["up","host","static"],"interface-name":'
    '"lo0"}, {"destination":"fe80::/10","gateway":"::1","flags":"UGRS", '
    '"flags_pretty": ["up","gateway","reject","static"],"interface-name":'
    '"lo0"}, {"destination":"fe80::%lo0/64","gateway":"link#3","flags":"U", '
    '"flags_pretty": ["up"],"interface-name":"lo0"}, {"destination":'
    '"fe80::1%lo0","gateway":"link#3","flags":"UHS", "flags_pretty": ["up",'
    '"host","static"],"interface-name":"lo0"}, {"destination":'
    '"fe80::%inet0/64","gateway":"link#4","flags":"U", "flags_pretty": '
    '["up"],"interface-name":"inet0"}, {"destination":'
    '"fe80::921b:eff:fe63:ef31%inet0","gateway":"link#4","flags":"UHS", '
    '"flags_pretty": ["up","host","static"],"interface-name":"lo0"}, {'
    '"destination":"fe80::%mgmt0/64","gateway":"link#5","flags":"U", '
    '"flags_pretty": ["up"],"interface-name":"mgmt0"}, {"destination":'
    '"fe80::921b:eff:fe63:f359%mgmt0","gateway":"link#5","flags":"UHS", '
    '"flags_pretty": ["up","host","static"],"interface-name":"lo0"}, {'
    '"destination":"fe80::%vnet0.97/64","gateway":"link#7","flags":"U", '
    '"flags_pretty": ["up"],"interface-name":"vnet0.97"}, {"destination":'
    '"fe80::1015:29ff:fecd:61a7%vnet0.97","gateway":"link#7","flags":"UHS", '
    '"flags_pretty": ["up","host","static"],"interface-name":"lo0"}, {'
    '"destination":"ff02::/16","gateway":"::1","flags":"UGRS", '
    '"flags_pretty": ["up","gateway","reject","static"],"interface-name":'
    '"lo0"}]}]}}}}')
