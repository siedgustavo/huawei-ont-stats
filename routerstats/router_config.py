#!/usr/bin/env python3
"""router_config.py - Lectura y escritura de configuración del router Huawei EG8021V5

Cubre las 3 secciones que se pisan con cada boot (la OLT reaplica su propia
config):
    - WLAN (WiFi 2.4GHz / 5GHz) enable/disable
    - Reserva DHCP estática (MAC -> IP)
    - DMZ (IP host)

Los endpoints fueron reversados a partir de capturas HAR reales del panel
web (ver PR/commit que introduce este archivo).
"""

from typing import Optional

from .router_info import _post, _get, _parse_all_constructors

# ---------------------------------------------------------------------------
# WLAN
# ---------------------------------------------------------------------------

# RadioInst 1 = 2.4GHz, RadioInst 2 = 5GHz (confirmado por captura HAR)
RADIO_2G = 1
RADIO_5G = 2


def set_wlan_radio_enable(opener, host: str, token: str, radio_inst: int, enable: bool):
    base = f"http://{host}"
    enable_val = "1" if enable else "0"
    band = "2G" if radio_inst == RADIO_2G else "5G"
    url = (
        f"{base}/html/amp/wlanbasic/set.cgi"
        f"?x=InternetGatewayDevice.X_HW_DEBUG.AMP.SetWifiCoverEnable"
        f"&y=InternetGatewayDevice.LANDevice.1.WiFi.Radio.{radio_inst}"
        f"&RequestFile=html/amp/wlanbasic/WlanBasic.asp"
    )
    data = {
        "x.Enable": enable_val,
        "x.RadioInst": str(radio_inst),
        "y.Enable": enable_val,
        "x.X_HW_Token": token,
    }
    referer = f"{base}/html/amp/wlanbasic/WlanBasic.asp?{band}"
    _post(opener, url, data=data, headers={"Referer": referer})


# ---------------------------------------------------------------------------
# DHCP static reservation
# ---------------------------------------------------------------------------

def get_dhcp_static_list(opener, host: str) -> list:
    """
    stDhcp(domain, Enable, ipAddress, macAddress)
    """
    base = f"http://{host}"
    raw = _get(opener, f"{base}/html/bbsp/dhcpstatic/dhcpstatic.asp").decode("utf-8", errors="replace")

    entries = []
    for a in _parse_all_constructors(raw, "stDhcp"):
        if len(a) < 4:
            continue
        entries.append({
            "domain":  a[0],
            "enabled": a[1],
            "ip":      a[2],
            "mac":     a[3],
        })
    return entries


def set_dhcp_reservation(opener, host: str, token: str, mac: str, ip: str, domain: Optional[str] = None):
    """Crea (domain=None) o actualiza (domain=<existing>) una reserva DHCP estática."""
    base = f"http://{host}"
    mac_norm = mac.lower()

    if domain:
        url = f"{base}/html/bbsp/dhcpstatic/set.cgi?x={domain}&RequestFile=html/bbsp/dhcpstatic/dhcpstatic.asp"
        data = {"x.Yiaddr": ip, "x.Chaddr": mac_norm, "x.X_HW_Token": token}
    else:
        url = (
            f"{base}/html/bbsp/dhcpstatic/add.cgi"
            f"?x=InternetGatewayDevice.LANDevice.1.LANHostConfigManagement.DHCPStaticAddress"
            f"&RequestFile=html/bbsp/dhcpstatic/dhcpstatic.asp"
        )
        data = {"x.Yiaddr": ip, "x.Chaddr": mac_norm, "x.Enable": "1", "x.X_HW_Token": token}

    referer = f"{base}/html/bbsp/dhcpstatic/dhcpstatic.asp"
    _post(opener, url, data=data, headers={"Referer": referer})


# ---------------------------------------------------------------------------
# DMZ
# ---------------------------------------------------------------------------

DEFAULT_WAN_DMZ_DOMAIN = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.2.WANPPPConnection.1"


def get_dmz_info(opener, host: str) -> list:
    """
    stDMZInfo(domain, DMZEnable, DMZHostIPAddress, flag)
    """
    base = f"http://{host}"
    raw = _get(opener, f"{base}/html/bbsp/dmz/dmz.asp").decode("utf-8", errors="replace")

    entries = []
    for a in _parse_all_constructors(raw, "stDMZInfo"):
        if len(a) < 3:
            continue
        entries.append({
            "domain":  a[0],
            "enabled": a[1],
            "ip":      a[2],
        })
    return entries


def set_dmz(opener, host: str, token: str, wan_domain: str, ip: str, exists: bool):
    """Crea (exists=False) o actualiza (exists=True) el mapeo DMZ para wan_domain."""
    base = f"http://{host}"
    action = "set.cgi" if exists else "add.cgi"
    url = f"{base}/html/bbsp/dmz/{action}?x={wan_domain}.X_HW_DMZ&RequestFile=html/bbsp/dmz/dmz.asp"
    data = {"x.DMZEnable": "1", "x.DMZHostIPAddress": ip, "x.X_HW_Token": token}
    referer = f"{base}/html/bbsp/dmz/dmz.asp"
    _post(opener, url, data=data, headers={"Referer": referer})


# ---------------------------------------------------------------------------
# Declarative reconciliation
# ---------------------------------------------------------------------------

def reconcile_once(opener, host: str, token: str, desired: dict, get_wlan_info) -> list:
    """Compara el estado actual del router con `desired` y aplica lo que falte.

    `desired` keys: wifi_2g_enabled, wifi_5g_enabled, dhcp_mac, dhcp_ip,
                     dmz_ip, wan_dmz_domain

    `get_wlan_info` se recibe como parámetro para evitar un import circular
    con router_info y para poder mockearlo fácil en tests.

    Devuelve la lista de acciones aplicadas (vacía si no había drift).
    """
    actions = []

    wlan = get_wlan_info(opener, host)
    if bool(wlan.get("enabled_2g")) != desired["wifi_2g_enabled"]:
        set_wlan_radio_enable(opener, host, token, RADIO_2G, desired["wifi_2g_enabled"])
        actions.append(f"wifi 2.4G -> {'ON' if desired['wifi_2g_enabled'] else 'OFF'}")
    if bool(wlan.get("enabled_5g")) != desired["wifi_5g_enabled"]:
        set_wlan_radio_enable(opener, host, token, RADIO_5G, desired["wifi_5g_enabled"])
        actions.append(f"wifi 5G -> {'ON' if desired['wifi_5g_enabled'] else 'OFF'}")

    dhcp_list = get_dhcp_static_list(opener, host)
    match = next((d for d in dhcp_list if d["mac"].lower() == desired["dhcp_mac"].lower()), None)
    if match is None:
        set_dhcp_reservation(opener, host, token, desired["dhcp_mac"], desired["dhcp_ip"])
        actions.append(f"dhcp reservation creada {desired['dhcp_mac']} -> {desired['dhcp_ip']}")
    elif match["ip"] != desired["dhcp_ip"]:
        set_dhcp_reservation(opener, host, token, desired["dhcp_mac"], desired["dhcp_ip"], domain=match["domain"])
        actions.append(f"dhcp reservation actualizada {desired['dhcp_mac']} -> {desired['dhcp_ip']}")

    dmz_list = get_dmz_info(opener, host)
    wan_domain = desired["wan_dmz_domain"]
    match = next((d for d in dmz_list if d["domain"].startswith(wan_domain)), None)
    exists = match is not None
    if not exists or match.get("ip") != desired["dmz_ip"] or match.get("enabled") != "1":
        set_dmz(opener, host, token, wan_domain, desired["dmz_ip"], exists)
        actions.append(f"dmz -> {desired['dmz_ip']}")

    return actions
