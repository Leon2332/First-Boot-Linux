#!/usr/bin/env python3
"""NetworkManager snapshot parsing — no D-Bus, no GTK."""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.net import (  # noqa: E402
    ethernet_detail,
    merge_access_points,
    parse_device_status,
    parse_radio,
    parse_wifi_connections,
    parse_wifi_list,
    pick_ethernet,
    split_nmcli,
    snapshot_from_text,
    uuid_for_ssid,
    wifi_key_mgmt,
    wifi_profile_settings,
    wifi_row_actions,
    NmError,
    WifiAP,
)


DEVICES = """\
enp34s0:ethernet:connected:Wired connection 1
wlp2s0:wifi:disconnected:
br-6650da91aede:bridge:connected (externally):br-6650da91aede
docker0:bridge:connected (externally):docker0
lo:loopback:connected (externally):lo
vethf308d94:ethernet:unmanaged:
"""


class SplitTests(unittest.TestCase):
    def test_plain(self) -> None:
        self.assertEqual(split_nmcli("a:b:c"), ["a", "b", "c"])

    def test_escaped_colon_in_ssid(self) -> None:
        self.assertEqual(
            split_nmcli("*:Cafe\\:Guest:80:WPA2"),
            ["*", "Cafe:Guest", "80", "WPA2"],
        )

    def test_trailing_empty(self) -> None:
        self.assertEqual(split_nmcli("wlp2s0:wifi:disconnected:"), ["wlp2s0", "wifi", "disconnected", ""])


class DeviceTests(unittest.TestCase):
    def test_ignores_virtual_and_picks_real_ethernet(self) -> None:
        devices = parse_device_status(DEVICES)
        eth = pick_ethernet(devices)
        self.assertEqual(eth.device, "enp34s0")
        self.assertTrue(eth.connected)
        self.assertTrue(eth.plugged)
        self.assertEqual(eth.connection, "Wired connection 1")

    def test_unplugged_ethernet(self) -> None:
        devices = parse_device_status("enp1s0:ethernet:unavailable:\n")
        eth = pick_ethernet(devices)
        self.assertEqual(eth.device, "enp1s0")
        self.assertFalse(eth.plugged)
        self.assertFalse(eth.connected)

    def test_no_ethernet(self) -> None:
        devices = parse_device_status("lo:loopback:unmanaged:\n")
        eth = pick_ethernet(devices)
        self.assertIsNone(eth.device)


class WifiListTests(unittest.TestCase):
    def test_merge_same_ssid_keeps_strongest_and_in_use(self) -> None:
        text = "\n".join(
            [
                " :Home-5G:40:WPA2:aa:aa:aa:aa:aa:aa",
                "*:Home-5G:90:WPA2:bb:bb:bb:bb:bb:bb",
                " :Cafe:10:--:cc:cc:cc:cc:cc:cc",
            ]
        )
        aps = parse_wifi_list(text)
        self.assertEqual([a.ssid for a in aps], ["Home-5G", "Cafe"])
        home = aps[0]
        self.assertTrue(home.in_use)
        self.assertEqual(home.signal, 90)
        self.assertTrue(aps[1].open)

    def test_skips_hidden(self) -> None:
        self.assertEqual(parse_wifi_list(" : :70:WPA2\n"), [])


class RadioTests(unittest.TestCase):
    def test_missing_hardware(self) -> None:
        hw, en = parse_radio("missing:enabled")
        self.assertFalse(hw)
        self.assertTrue(en)

    def test_present_disabled(self) -> None:
        hw, en = parse_radio("enabled:disabled")
        self.assertTrue(hw)
        self.assertFalse(en)


class SnapshotTests(unittest.TestCase):
    def test_wired_labels(self) -> None:
        snap = snapshot_from_text(DEVICES, "enabled:enabled", "")
        self.assertEqual(snap.kind, "wired")
        self.assertEqual(snap.label, "Wired")
        self.assertEqual(snap.sub, "Connected")
        self.assertEqual(snap.icon, "network-wired-symbolic.svg")
        self.assertTrue(snap.connected)

    def test_wifi_connected(self) -> None:
        devices = "wlp2s0:wifi:connected:Home-5G\nenp1s0:ethernet:unavailable:\n"
        wifi = "*:Home-5G:80:WPA2\n :Office:40:WPA2\n"
        snap = snapshot_from_text(devices, "enabled:enabled", wifi)
        self.assertEqual(snap.kind, "wifi")
        self.assertEqual(snap.label, "Home-5G")
        self.assertEqual(snap.wifi.ssid, "Home-5G")
        self.assertTrue(snap.access_points[0].in_use)

    def test_offline(self) -> None:
        snap = snapshot_from_text(
            "enp1s0:ethernet:unavailable:\nwlp2s0:wifi:disconnected:\n",
            "enabled:enabled",
            " :Office:40:WPA2\n",
        )
        self.assertEqual(snap.kind, "offline")
        self.assertEqual(snap.label, "Network")
        self.assertEqual(snap.sub, "Not connected")
        self.assertEqual(len(snap.access_points), 1)


class EthernetDetailTests(unittest.TestCase):
    def test_states(self) -> None:
        snap = snapshot_from_text(DEVICES, "enabled:enabled", "")
        self.assertEqual(ethernet_detail(snap.ethernet), ("Connected", "Disconnect"))
        snap = snapshot_from_text("enp1s0:ethernet:disconnected:\n", "enabled:enabled", "")
        self.assertEqual(ethernet_detail(snap.ethernet), ("Cable detected", "Connect"))
        snap = snapshot_from_text("enp1s0:ethernet:unavailable:\n", "enabled:enabled", "")
        self.assertEqual(ethernet_detail(snap.ethernet), ("Cable unplugged", None))


class ConnectionParseTests(unittest.TestCase):
    def test_wifi_names(self) -> None:
        text = "\n".join(
            [
                "Home-5G:aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb:802-11-wireless",
                "Wired connection 1:cccccccc-1111-2222-3333-dddddddddddd:802-3-ethernet",
                "Office-Secure:eeeeeeee-1111-2222-3333-ffffffffffff:wifi",
            ]
        )
        conns = parse_wifi_connections(text)
        self.assertEqual(set(conns), {"Home-5G", "Office-Secure"})
        self.assertEqual(conns["Home-5G"], "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb")

    def test_escaped_colon_in_name(self) -> None:
        conns = parse_wifi_connections(
            "Cafe\\:Guest:aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb:802-11-wireless\n"
        )
        self.assertEqual(set(conns), {"Cafe:Guest"})


class SavedSnapshotTests(unittest.TestCase):
    def test_saved_ssids_from_connections(self) -> None:
        devices = "wlp2s0:wifi:disconnected:\nenp1s0:ethernet:unavailable:\n"
        wifi = " :Home-5G:80:WPA2\n :Office-Secure:40:WPA2\n"
        conns = "Home-5G:aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb:802-11-wireless\n"
        snap = snapshot_from_text(devices, "enabled:enabled", wifi, conns)
        self.assertEqual(snap.saved_ssids, frozenset({"Home-5G"}))
        self.assertEqual(
            uuid_for_ssid(snap.saved_uuids, "Home-5G"),
            "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb",
        )
        self.assertIsNone(uuid_for_ssid(snap.saved_uuids, "Office-Secure"))

    def test_connected_ssid_counts_as_saved(self) -> None:
        devices = "wlp2s0:wifi:connected:Home-5G\n"
        wifi = "*:Home-5G:80:WPA2\n"
        snap = snapshot_from_text(devices, "enabled:enabled", wifi, "")
        self.assertIn("Home-5G", snap.saved_ssids)


class WifiKeyMgmtTests(unittest.TestCase):
    def test_open(self) -> None:
        self.assertIsNone(wifi_key_mgmt(""))
        self.assertIsNone(wifi_key_mgmt("--"))
        self.assertIsNone(wifi_key_mgmt("none"))

    def test_wpa2(self) -> None:
        self.assertEqual(wifi_key_mgmt("WPA2"), "wpa-psk")
        self.assertEqual(wifi_key_mgmt("WPA1 WPA2"), "wpa-psk")
        self.assertEqual(wifi_key_mgmt("WPA2 WPA3"), "wpa-psk")

    def test_wpa3_only(self) -> None:
        self.assertEqual(wifi_key_mgmt("WPA3"), "sae")
        self.assertEqual(wifi_key_mgmt("SAE"), "sae")

    def test_enterprise(self) -> None:
        self.assertEqual(wifi_key_mgmt("WPA2 802.1X"), "wpa-eap")

    def test_profile_sets_key_mgmt(self) -> None:
        self.assertEqual(
            wifi_profile_settings(security="WPA2", password="secret12"),
            ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", "secret12"],
        )
        self.assertEqual(
            wifi_profile_settings(security="WPA3", password="secret12"),
            ["wifi-sec.key-mgmt", "sae", "wifi-sec.psk", "secret12"],
        )
        self.assertEqual(wifi_profile_settings(security="--", password=None), [])

    def test_enterprise_profile_rejected(self) -> None:
        with self.assertRaises(NmError) as ctx:
            wifi_profile_settings(security="WPA2 802.1X", password="x")
        self.assertIn("Enterprise", str(ctx.exception))


class WifiRowActionTests(unittest.TestCase):
    def test_new_secure(self) -> None:
        self.assertEqual(
            wifi_row_actions(secure=True, in_use=False, saved=False),
            (True, True, False),
        )

    def test_saved_secure(self) -> None:
        self.assertEqual(
            wifi_row_actions(secure=True, in_use=False, saved=True),
            (True, True, True),
        )

    def test_open(self) -> None:
        self.assertEqual(
            wifi_row_actions(secure=False, in_use=False, saved=False),
            (False, True, False),
        )

    def test_connected_saved(self) -> None:
        self.assertEqual(
            wifi_row_actions(secure=True, in_use=True, saved=True),
            (False, False, True),
        )


class MergeEdgeTests(unittest.TestCase):
    def test_in_use_weaker_signal_still_marked(self) -> None:
        aps = merge_access_points(
            [
                WifiAP("A", 90, "WPA2", False),
                WifiAP("A", 20, "WPA2", True),
            ]
        )
        self.assertEqual(len(aps), 1)
        self.assertTrue(aps[0].in_use)
        self.assertEqual(aps[0].signal, 90)


if __name__ == "__main__":
    unittest.main()
