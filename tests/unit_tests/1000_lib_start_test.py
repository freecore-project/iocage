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
import mock
import pytest
import iocage_lib.ioc_start as ioc_start


@pytest.mark.parametrize('ifconfig_output,expected', [
    ("""epair0b: flags=8863<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> metric 0 mtu 1500
        description: jail side interface
        options=8<VLAN_MTU>
        inet 192.0.2.10 netmask 0xffffff00 broadcast 192.0.2.255
        groups: epair
""", ('192.0.2.10', 24)),
    ("""epair0b: flags=8863<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> metric 0 mtu 1500
        inet 198.51.100.12 netmask 255.255.255.128 broadcast 198.51.100.127
""", ('198.51.100.12', 25)),
])
def test_parse_dhcp_address_from_ifconfig_inet(ifconfig_output, expected):
    assert ioc_start.parse_dhcp_address(ifconfig_output.encode()) == expected


def test_parse_dhcp_address_raises_without_inet():
    with pytest.raises(ValueError):
        ioc_start.parse_dhcp_address(
            b'epair0b: flags=8863<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST>\n'
        )


def test_find_vnet_default_route_interface_matches_configured_address():
    assert ioc_start.find_vnet_default_route_interface(
        ['vnet0:bridge0', 'vnet1:bridge1'],
        'vnet1|2001:db8::10/64',
    ) == 'vnet1'


def test_find_vnet_default_route_interface_falls_back_to_vnet0():
    assert ioc_start.find_vnet_default_route_interface(
        ['vnet2:bridge2'],
        '2001:db8::10/64',
    ) == 'vnet0'


@mock.patch('iocage_lib.ioc_common.checkoutput')
def test_should_return_mtu_of_first_member(mock_checkoutput):
    mock_checkoutput.side_effect = [bridge_if_config, member_if_config]

    mtu = ioc_start.IOCStart("", "", unit_test=True).find_bridge_mtu('bridge0')
    assert mtu == '1500'
    mock_checkoutput.assert_has_calls([mock.call(["ifconfig", "bridge0"]),
                                       mock.call(["ifconfig", "bge0"])])


@mock.patch('iocage_lib.ioc_common.checkoutput')
def test_should_return_mtu_of_first_member_with_description(mock_checkoutput):
    mock_checkoutput.side_effect = [bridge_with_description_if_config,
                                    member_if_config]

    mtu = ioc_start.IOCStart("", "", unit_test=True).find_bridge_mtu('bridge0')
    assert mtu == '1500'
    mock_checkoutput.assert_has_calls([mock.call(["ifconfig", "bridge0"]),
                                       mock.call(["ifconfig", "bge0"])])


@mock.patch('iocage_lib.ioc_common.checkoutput')
def test_should_return_default_mtu_if_no_members(mock_checkoutput):
    mock_checkoutput.side_effect = [bridge_with_no_members_if_config,
                                    member_if_config]

    # IOCStart.get() is not implemented in test mode. We need it for this test.
    # So provide a dummy implementation which gives us the default MTU.
    def _mock_iocstart_get(prop):
        if prop=='vnet_default_mtu':
            return "1500"
        raise AttributeError(prop)

    iocs = ioc_start.IOCStart("", "", unit_test=True)
    iocs.get = _mock_iocstart_get
    mtu = iocs.find_bridge_mtu('bridge0')
    assert mtu == '1500'
    mock_checkoutput.assert_called_with(["ifconfig", "bridge0"])


@mock.patch('iocage_lib.ioc_common.logit')
@pytest.mark.parametrize('test_input,expected', [
    ({'host_gateways': {'ipv4': {'gateway': '217.29.43.254',
                                 'interface': 'inet0'},
                        'ipv6': {'gateway': None,
                                 'interface': None}}},
     'inet0'),
    ({'host_gateways': {'ipv4': {'gateway': '217.29.43.254',
                                 'interface': 'inet0'},
                        'ipv6': {'gateway': 'fe80::8%mgmt0',
                                 'interface': 'mgmt0'}}},
     'inet0'),
    ({'host_gateways': {'ipv4': {'gateway': None,
                                 'interface': None},
                        'ipv6': {'gateway': 'fe80::8%mgmt0',
                                 'interface': 'mgmt0'}}},
     'mgmt0'),
    ({'host_gateways': {'ipv4': {'gateway': None,
                                 'interface': None},
                        'ipv6': {'gateway': None,
                                 'interface': None}}},
     Exception)])
def test_should_return_default_interface(mock_logit, test_input, expected):
    iocstart = ioc_start.IOCStart("", "", unit_test=True)
    iocstart.host_gateways = test_input['host_gateways']
    actual = iocstart.get_default_interface()
    if expected != Exception:
        assert actual == expected
        mock_logit.assert_not_called()
    else:
        mock_logit.assert_called_once_with({'level': 'EXCEPTION',
                                            'message': 'No default interface found'},
                                           _callback=None,
                                           silent=False)


@pytest.mark.parametrize('test_input,expected', [
    ({'host_gateways': {'ipv4': {'gateway': None,
                                 'interface': None},
                        'ipv6': {'gateway': None,
                                 'interface': None}}},
     {'ipv4': 'none',
      'ipv6': 'none'}),
    ({'host_gateways': {'ipv4': {'gateway': '217.29.43.254',
                                 'interface': 'inet0'},
                        'ipv6': {'gateway': 'fe80::8%inet0',
                                 'interface': 'inet0'}}},
     {'ipv4': '217.29.43.254',
      'ipv6': 'fe80::8%inet0'}),
    ({'host_gateways': {'ipv4': {'gateway': None,
                                 'interface': None},
                        'ipv6': {'gateway': 'fe80::8%mgmt0',
                                 'interface': 'mgmt0'}}},
     {'ipv4': 'none',
      'ipv6': 'fe80::8%mgmt0'}),
    ({'host_gateways': {'ipv4': {'gateway': None,
                                 'interface': None},
                        'ipv6': {'gateway': 'fe80::8%inet0',
                                 'interface': 'inet0'}}},
     {'ipv4': 'none',
      'ipv6': 'fe80::8%inet0'}),
    ({'host_gateways': {'ipv4': {'gateway': None,
                                 'interface': None},
                        'ipv6': {'gateway': 'fe80::8%inet0',
                                 'interface': 'inet0'}}},
     {'ipv4': 'none',
      'ipv6': 'fe80::8%inet0'})])
def test_should_return_default_gateway(test_input, expected):
    iocstart = ioc_start.IOCStart("", "", unit_test=True)
    iocstart.host_gateways = test_input['host_gateways']
    assert iocstart.get_default_gateway() == expected['ipv4']
    assert iocstart.get_default_gateway('ipv4') == expected['ipv4']
    assert iocstart.get_default_gateway('ipv6') == expected['ipv6']


@mock.patch('iocage_lib.ioc_common.checkoutput')
def test_start_network_vnet_addr_configures_static_ipv6_with_ipv4_dhcp(mock_checkoutput):
    iocstart = ioc_start.IOCStart("", "", unit_test=True)
    iocstart.exec_fib = '0'
    iocstart.ip4_addr = 'DHCP'
    iocstart.uuid = 'dhcpv6'
    iocstart.get = lambda prop: 1 if prop == 'dhcp' else None

    assert iocstart.start_network_vnet_addr(
        'vnet0', '2001:db8::10/64', 'none', ipv6=True
    ) is None
    mock_checkoutput.assert_called_once_with([
        'setfib', '0', 'jexec', 'ioc-dhcpv6',
        'ifconfig', 'epair0b', 'inet6', '2001:db8::10/64', 'up'
    ], stderr=ioc_start.su.STDOUT)


@mock.patch('iocage_lib.ioc_common.checkoutput')
@mock.patch('iocage_lib.ioc_start.su.Popen')
def test_start_network_vnet_iface_disables_jail_epair_tx_checksum_offload(
        mock_popen, mock_checkoutput):
    process = mock.Mock()
    process.communicate.return_value = (b'epair0a\n',)
    mock_popen.return_value = process

    iocstart = ioc_start.IOCStart("", "", unit_test=True)
    iocstart.exec_fib = '0'
    iocstart.ip6_addr = 'none'
    iocstart.uuid = 'testnat'
    iocstart.get = lambda prop: {
        'vnet_default_interface': 'em0',
        'vnet1_mac': '020000000001 020000000002',
    }[prop]

    assert iocstart.start_network_vnet_iface(
        'vnet1', 'bridge0', '1500', '3', nat_addr='192.0.2.1'
    ) is None
    mock_checkoutput.assert_has_calls([
        mock.call([
            'setfib', '0', 'jexec', 'ioc-testnat',
            'ifconfig', 'epair0b', 'name', 'epair1b'
        ], stderr=ioc_start.su.STDOUT),
        mock.call([
            'setfib', '0', 'jexec', 'ioc-testnat',
            'ifconfig', 'epair1b', 'link', '020000000002'
        ], stderr=ioc_start.su.STDOUT),
        mock.call([
            'setfib', '0', 'jexec', 'ioc-testnat',
            'ifconfig', 'epair1b', '-txcsum', '-txcsum6'
        ], stderr=ioc_start.su.STDOUT),
    ])


bridge_if_config = """bridge0: flags=8843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> metric 0 mtu 1500
        ether 00:00:00:00:00:00
        nd6 options=1<PERFORMNUD>
        groups: bridge
        id 00:00:00:00:00:00 priority 32768 hellotime 2 fwddelay 15
        maxage 20 holdcnt 6 proto rstp maxaddr 2000 timeout 1200
        root id 00:00:00:00:00:00 priority 32768 ifcost 0 port 0
            member: bge0 flags=143<LEARNING,DISCOVER,AUTOEDGE,AUTOPTP>
            ifmaxaddr 0 port 1 priority 128 path cost 20000
"""

bridge_with_description_if_config = """bridge0: flags=8843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> metric 0 mtu 1500
        description: first-bridge
        ether 00:00:00:00:00:00
        nd6 options=1<PERFORMNUD>
        groups: bridge
        id 00:00:00:00:00:00 priority 32768 hellotime 2 fwddelay 15
        maxage 20 holdcnt 6 proto rstp maxaddr 2000 timeout 1200
        root id 00:00:00:00:00:00 priority 32768 ifcost 0 port 0
            member: bge0 flags=143<LEARNING,DISCOVER,AUTOEDGE,AUTOPTP>
            ifmaxaddr 0 port 1 priority 128 path cost 20000
"""

bridge_with_no_members_if_config = """bridge0: flags=8843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> metric 0 mtu 1500
        description: first-bridge
        ether 00:00:00:00:00:00
        nd6 options=1<PERFORMNUD>
        groups: bridge
        id 00:00:00:00:00:00 priority 32768 hellotime 2 fwddelay 15
        maxage 20 holdcnt 6 proto rstp maxaddr 2000 timeout 1200
        root id 00:00:00:00:00:00 priority 32768 ifcost 0 port 0
"""

member_if_config = """bge0: flags=8943<UP,BROADCAST,RUNNING,PROMISC,SIMPLEX,MULTICAST> metric 0 mtu 1500
        options=c019b<RXCSUM,TXCSUM,VLAN_MTU,VLAN_HWTAGGING,VLAN_HWCSUM,TSO4,VLAN_HWTSO,LINKSTATE>
        ether 00:00:00:00:00:00
        inet6 fe80::0000:0000:0000:0000%bge0 prefixlen 64 scopeid 0x1
        inet 10.2.3.4 netmask 0xffffff00 broadcast 10.2.3.255
        nd6 options=21<PERFORMNUD,AUTO_LINKLOCAL>
        media: Ethernet autoselect (1000baseT <full-duplex>)
        status: active
"""
