"""Tests for NetworkProfile detection and LAN optimization features"""

import pytest
from vnc_lib.server_utils import NetworkProfile, detect_network_profile


class TestNetworkProfile:
    """Test network profile detection"""

    # Localhost IPv4
    def test_localhost_ipv4(self):
        assert detect_network_profile("127.0.0.1") == NetworkProfile.LOCALHOST

    def test_localhost_ipv4_other(self):
        assert detect_network_profile("127.0.0.2") == NetworkProfile.LOCALHOST

    def test_localhost_ipv4_full_range(self):
        assert detect_network_profile("127.255.255.255") == NetworkProfile.LOCALHOST

    # Localhost IPv6
    def test_localhost_ipv6(self):
        assert detect_network_profile("::1") == NetworkProfile.LOCALHOST

    # Private network 10.x.x.x
    def test_lan_10_network(self):
        assert detect_network_profile("10.0.0.1") == NetworkProfile.LAN

    def test_lan_10_network_other(self):
        assert detect_network_profile("10.255.255.255") == NetworkProfile.LAN

    # Private network 172.16-31.x.x
    def test_lan_172_16(self):
        assert detect_network_profile("172.16.0.1") == NetworkProfile.LAN

    def test_lan_172_31(self):
        assert detect_network_profile("172.31.255.255") == NetworkProfile.LAN

    def test_wan_172_15(self):
        """172.15.x.x is NOT private"""
        assert detect_network_profile("172.15.0.1") == NetworkProfile.WAN

    def test_wan_172_32(self):
        """172.32.x.x is NOT private"""
        assert detect_network_profile("172.32.0.1") == NetworkProfile.WAN

    # Private network 192.168.x.x
    def test_lan_192_168(self):
        assert detect_network_profile("192.168.0.1") == NetworkProfile.LAN

    def test_lan_192_168_other(self):
        assert detect_network_profile("192.168.1.100") == NetworkProfile.LAN

    # Link-local
    def test_lan_link_local_ipv4(self):
        assert detect_network_profile("169.254.1.1") == NetworkProfile.LAN

    def test_lan_link_local_ipv6(self):
        assert detect_network_profile("fe80::1") == NetworkProfile.LAN

    # Public IPs -> WAN
    def test_wan_public_ip(self):
        assert detect_network_profile("8.8.8.8") == NetworkProfile.WAN

    def test_wan_public_ip_other(self):
        assert detect_network_profile("1.1.1.1") == NetworkProfile.WAN

    def test_wan_public_ip_class_b(self):
        assert detect_network_profile("142.250.80.46") == NetworkProfile.WAN

    # Invalid input
    def test_invalid_ip_returns_wan(self):
        assert detect_network_profile("not-an-ip") == NetworkProfile.WAN

    def test_empty_string_returns_wan(self):
        assert detect_network_profile("") == NetworkProfile.WAN


class TestNetworkProfileEnum:
    """Test NetworkProfile enum values"""

    def test_localhost_value(self):
        assert NetworkProfile.LOCALHOST.value == "localhost"

    def test_lan_value(self):
        assert NetworkProfile.LAN.value == "lan"

    def test_wan_value(self):
        assert NetworkProfile.WAN.value == "wan"

    def test_from_string(self):
        assert NetworkProfile("localhost") == NetworkProfile.LOCALHOST
        assert NetworkProfile("lan") == NetworkProfile.LAN
        assert NetworkProfile("wan") == NetworkProfile.WAN
