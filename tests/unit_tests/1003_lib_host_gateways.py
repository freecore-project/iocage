from unittest.mock import patch
from iocage_lib.ioc_common import get_host_gateways, retrieve_ip4_for_jail


@patch('iocage_lib.ioc_common.checkoutput')
def test_01_get_host_gateways(mock_checkoutput):
    mock_checkoutput.side_effect = [netstat_output]
    assert get_host_gateways() == \
        {'ipv4': {'gateway': '217.29.43.254', 'interface': 'inet0'},
         'ipv6': {'gateway': 'fe80::8%inet0', 'interface': 'inet0'}}


@patch('iocage_lib.ioc_common.checkoutput')
def test_get_host_gateways_tolerates_missing_ipv6_family(mock_checkoutput):
    mock_checkoutput.side_effect = [ipv4_only_netstat_output]
    assert get_host_gateways() == \
        {'ipv4': {'gateway': '217.29.43.254', 'interface': 'inet0'},
         'ipv6': {'gateway': None, 'interface': None}}


@patch('iocage_lib.ioc_common.os.geteuid', return_value=0)
@patch('iocage_lib.ioc_common.su.check_output')
def test_retrieve_ip4_for_jail_parses_dhcp_inet_line(mock_check_output, _mock_geteuid):
    mock_check_output.return_value = b"""epair1b: flags=8863<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> metric 0 mtu 1500
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


netstat_output = '{"statistics": {"route-information": {"route-table": {"rt-family": [{"address-family":"Internet", "rt-entry": [{"destination":"default","gateway":"217.29.43.254","flags":"UGS", "flags_pretty": ["up","gateway","static"],"interface-name":"inet0"}, {"destination":"10.5.0.0/16","gateway":"link#5","flags":"U", "flags_pretty": ["up"],"interface-name":"mgmt0"}, {"destination":"10.5.105.29","gateway":"link#5","flags":"UHS", "flags_pretty": ["up","host","static"],"interface-name":"lo0"}, {"destination":"127.0.0.1","gateway":"lo0","flags":"UHS", "flags_pretty": ["up","host","static"],"interface-name":"lo0"}, {"destination":"217.29.42.0/23","gateway":"link#4","flags":"U", "flags_pretty": ["up"],"interface-name":"inet0"}, {"destination":"217.29.42.186","gateway":"link#4","flags":"UHS", "flags_pretty": ["up","host","static"],"interface-name":"lo0"}]}, {"address-family":"Internet6", "rt-entry": [{"destination":"::/96","gateway":"::1","flags":"UGRS", "flags_pretty": ["up","gateway","reject","static"],"interface-name":"lo0"}, {"destination":"default","gateway":"fe80::8%inet0","flags":"UGS", "flags_pretty": ["up","gateway","static"],"interface-name":"inet0"}, {"destination":"::1","gateway":"lo0","flags":"UHS", "flags_pretty": ["up","host","static"],"interface-name":"lo0"}, {"destination":"::ffff:0.0.0.0/96","gateway":"::1","flags":"UGRS", "flags_pretty": ["up","gateway","reject","static"],"interface-name":"lo0"}, {"destination":"2a00:b580:8000:8::/64","gateway":"link#4","flags":"U", "flags_pretty": ["up"],"interface-name":"inet0"}, {"destination":"2a00:b580:8000:8:9d6:2f93:3504:d4c9","gateway":"link#4","flags":"UHS", "flags_pretty": ["up","host","static"],"interface-name":"lo0"}, {"destination":"fe80::/10","gateway":"::1","flags":"UGRS", "flags_pretty": ["up","gateway","reject","static"],"interface-name":"lo0"}, {"destination":"fe80::%lo0/64","gateway":"link#3","flags":"U", "flags_pretty": ["up"],"interface-name":"lo0"}, {"destination":"fe80::1%lo0","gateway":"link#3","flags":"UHS", "flags_pretty": ["up","host","static"],"interface-name":"lo0"}, {"destination":"fe80::%inet0/64","gateway":"link#4","flags":"U", "flags_pretty": ["up"],"interface-name":"inet0"}, {"destination":"fe80::921b:eff:fe63:ef31%inet0","gateway":"link#4","flags":"UHS", "flags_pretty": ["up","host","static"],"interface-name":"lo0"}, {"destination":"fe80::%mgmt0/64","gateway":"link#5","flags":"U", "flags_pretty": ["up"],"interface-name":"mgmt0"}, {"destination":"fe80::921b:eff:fe63:f359%mgmt0","gateway":"link#5","flags":"UHS", "flags_pretty": ["up","host","static"],"interface-name":"lo0"}, {"destination":"fe80::%vnet0.97/64","gateway":"link#7","flags":"U", "flags_pretty": ["up"],"interface-name":"vnet0.97"}, {"destination":"fe80::1015:29ff:fecd:61a7%vnet0.97","gateway":"link#7","flags":"UHS", "flags_pretty": ["up","host","static"],"interface-name":"lo0"}, {"destination":"ff02::/16","gateway":"::1","flags":"UGRS", "flags_pretty": ["up","gateway","reject","static"],"interface-name":"lo0"}]}]}}}}'
ipv4_only_netstat_output = '{"statistics": {"route-information": {"route-table": {"rt-family": [{"address-family":"Internet", "rt-entry": [{"destination":"default","gateway":"217.29.43.254","flags":"UGS","interface-name":"inet0"}]}]}}}}'
