#!/usr/bin/env python3
"""Tests for router_config.py – parsing and declarative reconciliation."""

import unittest
from unittest.mock import patch, MagicMock

from routerstats.router_config import (
    get_dhcp_static_list,
    get_dmz_info,
    set_wlan_radio_enable,
    set_dhcp_reservation,
    set_dmz,
    reconcile_once,
    RADIO_2G,
    RADIO_5G,
    DEFAULT_WAN_DMZ_DOMAIN,
)

FAKE_OPENER = MagicMock()
FAKE_TOKEN = "fake_token_abc123"
HOST = "192.168.18.1"

DHCPSTATIC_HTML = """
var Dhcps = new Array(new stDhcp("InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress.1","1","192\\x2e168\\x2e18\\x2e2","08\\x3a55\\x3a31\\x3aa7\\x3ac7\\x3af5"),null)
"""

DHCPSTATIC_EMPTY_HTML = """
var Dhcps = new Array(null)
"""

DMZ_HTML = """
var IpDmzInfo = new Array(null);
var PppDmzInfo = new Array(new stDMZInfo("InternetGatewayDevice.WANDevice.1.WANConnectionDevice.2.WANPPPConnection.1.X_HW_DMZ","1","192\\x2e168\\x2e18\\x2e2"),null);
"""

DMZ_EMPTY_HTML = """
var IpDmzInfo = new Array(null);
var PppDmzInfo = new Array(null);
"""


class TestParsers(unittest.TestCase):

    @patch("routerstats.router_config._get")
    def test_get_dhcp_static_list(self, mock_get):
        mock_get.return_value = DHCPSTATIC_HTML.encode()
        entries = get_dhcp_static_list(FAKE_OPENER, HOST)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["ip"], "192.168.18.2")
        self.assertEqual(entries[0]["mac"], "08:55:31:a7:c7:f5")
        self.assertEqual(entries[0]["domain"], "InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress.1")

    @patch("routerstats.router_config._get")
    def test_get_dhcp_static_list_empty(self, mock_get):
        mock_get.return_value = DHCPSTATIC_EMPTY_HTML.encode()
        entries = get_dhcp_static_list(FAKE_OPENER, HOST)
        self.assertEqual(entries, [])

    @patch("routerstats.router_config._get")
    def test_get_dmz_info(self, mock_get):
        mock_get.return_value = DMZ_HTML.encode()
        entries = get_dmz_info(FAKE_OPENER, HOST)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["ip"], "192.168.18.2")
        self.assertEqual(entries[0]["enabled"], "1")
        self.assertTrue(entries[0]["domain"].startswith(DEFAULT_WAN_DMZ_DOMAIN))

    @patch("routerstats.router_config._get")
    def test_get_dmz_info_empty(self, mock_get):
        mock_get.return_value = DMZ_EMPTY_HTML.encode()
        entries = get_dmz_info(FAKE_OPENER, HOST)
        self.assertEqual(entries, [])


class TestSetters(unittest.TestCase):

    @patch("routerstats.router_config._post")
    def test_set_wlan_radio_enable_off(self, mock_post):
        set_wlan_radio_enable(FAKE_OPENER, HOST, FAKE_TOKEN, RADIO_2G, False)
        url, kwargs = mock_post.call_args[0][1], mock_post.call_args[1]
        self.assertIn("Radio.1", url)
        self.assertIn("SetWifiCoverEnable", url)
        data = mock_post.call_args[1]["data"]
        self.assertEqual(data["x.Enable"], "0")
        self.assertEqual(data["x.RadioInst"], "1")
        self.assertEqual(data["y.Enable"], "0")
        self.assertEqual(data["x.X_HW_Token"], FAKE_TOKEN)

    @patch("routerstats.router_config._post")
    def test_set_wlan_radio_enable_5g_on(self, mock_post):
        set_wlan_radio_enable(FAKE_OPENER, HOST, FAKE_TOKEN, RADIO_5G, True)
        url = mock_post.call_args[0][1]
        data = mock_post.call_args[1]["data"]
        self.assertIn("Radio.2", url)
        self.assertEqual(data["x.RadioInst"], "2")
        self.assertEqual(data["x.Enable"], "1")

    @patch("routerstats.router_config._post")
    def test_set_dhcp_reservation_add(self, mock_post):
        set_dhcp_reservation(FAKE_OPENER, HOST, FAKE_TOKEN, "08:55:31:A7:C7:F5", "192.168.18.2")
        url = mock_post.call_args[0][1]
        data = mock_post.call_args[1]["data"]
        self.assertIn("add.cgi", url)
        self.assertEqual(data["x.Yiaddr"], "192.168.18.2")
        self.assertEqual(data["x.Chaddr"], "08:55:31:a7:c7:f5")
        self.assertEqual(data["x.Enable"], "1")

    @patch("routerstats.router_config._post")
    def test_set_dhcp_reservation_update(self, mock_post):
        domain = "InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress.1"
        set_dhcp_reservation(FAKE_OPENER, HOST, FAKE_TOKEN, "08:55:31:A7:C7:F5", "192.168.18.5", domain=domain)
        url = mock_post.call_args[0][1]
        data = mock_post.call_args[1]["data"]
        self.assertIn("set.cgi", url)
        self.assertIn(domain, url)
        self.assertEqual(data["x.Yiaddr"], "192.168.18.5")
        self.assertNotIn("x.Enable", data)

    @patch("routerstats.router_config._post")
    def test_set_dmz_add(self, mock_post):
        set_dmz(FAKE_OPENER, HOST, FAKE_TOKEN, DEFAULT_WAN_DMZ_DOMAIN, "192.168.18.2", exists=False)
        url = mock_post.call_args[0][1]
        data = mock_post.call_args[1]["data"]
        self.assertIn("add.cgi", url)
        self.assertEqual(data["x.DMZEnable"], "1")
        self.assertEqual(data["x.DMZHostIPAddress"], "192.168.18.2")

    @patch("routerstats.router_config._post")
    def test_set_dmz_update(self, mock_post):
        set_dmz(FAKE_OPENER, HOST, FAKE_TOKEN, DEFAULT_WAN_DMZ_DOMAIN, "192.168.18.2", exists=True)
        url = mock_post.call_args[0][1]
        self.assertIn("set.cgi", url)


DESIRED = {
    "wifi_2g_enabled": False,
    "wifi_5g_enabled": False,
    "dhcp_mac": "08:55:31:A7:C7:F5",
    "dhcp_ip": "192.168.18.2",
    "dmz_ip": "192.168.18.2",
    "wan_dmz_domain": DEFAULT_WAN_DMZ_DOMAIN,
}


class TestReconcileOnce(unittest.TestCase):

    def _wlan_info(self, enabled_2g, enabled_5g):
        return lambda opener, host: {"enabled_2g": enabled_2g, "enabled_5g": enabled_5g}

    @patch("routerstats.router_config.set_dmz")
    @patch("routerstats.router_config.set_dhcp_reservation")
    @patch("routerstats.router_config.set_wlan_radio_enable")
    @patch("routerstats.router_config.get_dmz_info")
    @patch("routerstats.router_config.get_dhcp_static_list")
    def test_no_drift_no_actions(self, mock_dhcp_list, mock_dmz_list, mock_set_wlan, mock_set_dhcp, mock_set_dmz):
        mock_dhcp_list.return_value = [{
            "domain": "InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress.1",
            "enabled": "1", "ip": "192.168.18.2", "mac": "08:55:31:a7:c7:f5",
        }]
        mock_dmz_list.return_value = [{
            "domain": DEFAULT_WAN_DMZ_DOMAIN + ".X_HW_DMZ", "enabled": "1", "ip": "192.168.18.2",
        }]
        actions = reconcile_once(FAKE_OPENER, HOST, FAKE_TOKEN, DESIRED, self._wlan_info(False, False))
        self.assertEqual(actions, [])
        mock_set_wlan.assert_not_called()
        mock_set_dhcp.assert_not_called()
        mock_set_dmz.assert_not_called()

    @patch("routerstats.router_config.set_dmz")
    @patch("routerstats.router_config.set_dhcp_reservation")
    @patch("routerstats.router_config.set_wlan_radio_enable")
    @patch("routerstats.router_config.get_dmz_info")
    @patch("routerstats.router_config.get_dhcp_static_list")
    def test_full_drift_applies_everything(self, mock_dhcp_list, mock_dmz_list, mock_set_wlan, mock_set_dhcp, mock_set_dmz):
        mock_dhcp_list.return_value = []
        mock_dmz_list.return_value = []
        actions = reconcile_once(FAKE_OPENER, HOST, FAKE_TOKEN, DESIRED, self._wlan_info(True, True))
        self.assertEqual(len(actions), 4)  # 2g off, 5g off, dhcp created, dmz created
        self.assertEqual(mock_set_wlan.call_count, 2)
        mock_set_dhcp.assert_called_once_with(FAKE_OPENER, HOST, FAKE_TOKEN, "08:55:31:A7:C7:F5", "192.168.18.2")
        mock_set_dmz.assert_called_once_with(FAKE_OPENER, HOST, FAKE_TOKEN, DEFAULT_WAN_DMZ_DOMAIN, "192.168.18.2", False)

    @patch("routerstats.router_config.set_dmz")
    @patch("routerstats.router_config.set_dhcp_reservation")
    @patch("routerstats.router_config.set_wlan_radio_enable")
    @patch("routerstats.router_config.get_dmz_info")
    @patch("routerstats.router_config.get_dhcp_static_list")
    def test_dhcp_ip_drift_updates_existing_domain(self, mock_dhcp_list, mock_dmz_list, mock_set_wlan, mock_set_dhcp, mock_set_dmz):
        domain = "InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress.1"
        mock_dhcp_list.return_value = [{
            "domain": domain, "enabled": "1", "ip": "192.168.18.99", "mac": "08:55:31:a7:c7:f5",
        }]
        mock_dmz_list.return_value = [{
            "domain": DEFAULT_WAN_DMZ_DOMAIN + ".X_HW_DMZ", "enabled": "1", "ip": "192.168.18.2",
        }]
        actions = reconcile_once(FAKE_OPENER, HOST, FAKE_TOKEN, DESIRED, self._wlan_info(False, False))
        self.assertEqual(len(actions), 1)
        mock_set_dhcp.assert_called_once_with(FAKE_OPENER, HOST, FAKE_TOKEN, "08:55:31:A7:C7:F5", "192.168.18.2", domain=domain)


if __name__ == "__main__":
    unittest.main()
