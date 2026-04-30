#!/usr/bin/env python3
"""
router_info.py - Estado completo del router Huawei EG8021V5

Secciones: Device Info, ONT/PON, Optical, WAN + Tráfico, ETH Ports, WLAN, LAN Clients

Uso:
    python3 router_info.py
    python3 router_info.py --host 192.168.18.1 --user Epadmin --pass adminEp
    python3 router_info.py --json
    python3 router_info.py --watch 30
"""

import argparse
import base64
import json as _json
import re
import sys
import time
from typing import Optional
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor
from http.cookiejar import CookieJar


# ---------------------------------------------------------------------------
# Helpers HTTP
# ---------------------------------------------------------------------------

def _post(opener, url, data: Optional[dict] = None, headers: Optional[dict] = None) -> bytes:
    body = urlencode(data).encode() if data else b""
    hdrs = {
        "User-Agent": "Mozilla/5.0 (router_info.py)",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
    }
    if headers:
        hdrs.update(headers)
    req = Request(url, data=body, headers=hdrs, method="POST")
    with opener.open(req, timeout=10) as r:
        return r.read()


def _get(opener, url, referer: str = "") -> bytes:
    hdrs = {"User-Agent": "Mozilla/5.0 (router_info.py)"}
    if referer:
        hdrs["Referer"] = referer
    req = Request(url, headers=hdrs)
    with opener.open(req, timeout=10) as r:
        return r.read()


# ---------------------------------------------------------------------------
# Helpers JS parsing
# ---------------------------------------------------------------------------

def _decode_js(s: str) -> str:
    try:
        return s.encode().decode("unicode_escape")
    except Exception:
        return s


def _parse_constructor(raw: str, name: str) -> list:
    """Primer new Name(...) encontrado."""
    m = re.search(r'new\s+' + re.escape(name) + r'\s*\(([^)]*)\)', raw)
    if not m:
        return []
    return [_decode_js(a.group(1)) for a in re.finditer(r'"((?:[^"\\]|\\.)*)"', m.group(1))]


def _parse_all_constructors(raw: str, name: str) -> list:
    """Todos los new Name(...) encontrados."""
    results = []
    for m in re.finditer(r'new\s+' + re.escape(name) + r'\s*\(([^)]*)\)', raw):
        args = [_decode_js(a.group(1)) for a in re.finditer(r'"((?:[^"\\]|\\.)*)"', m.group(1))]
        if args:
            results.append(args)
    return results


def _js_var(raw: str, name: str) -> str:
    m = re.search(r'var\s+' + re.escape(name) + r"\s*=\s*['\"]([^'\"]*)['\"]", raw)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login(host: str, username: str, password: str):
    base = f"http://{host}"
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))

    pre_token = _get(opener, f"{base}/html/ssmp/common/getRandString.asp").decode("utf-8", errors="replace").strip()
    if not pre_token:
        raise RuntimeError("No se pudo obtener token pre-login.")

    pw_b64 = base64.b64encode(password.encode()).decode()
    _post(opener, f"{base}/login.cgi", data={
        "UserName": username,
        "PassWord": pw_b64,
        "Language": "english",
        "x.X_HW_Token": pre_token,
    }, headers={"Referer": f"{base}/"})

    session_token = _get(opener, f"{base}/html/ssmp/common/GetRandToken.asp").decode("utf-8", errors="replace").strip()
    if not session_token or "<html" in session_token.lower():
        raise RuntimeError("Login fallido. Verificá usuario/contraseña.")

    return opener, session_token


# ---------------------------------------------------------------------------
# Device Info
# ---------------------------------------------------------------------------

def get_device_info(opener, host: str) -> dict:
    base = f"http://{host}"
    raw = _get(opener, f"{base}/html/ssmp/deviceinfo/deviceinfo.asp").decode("utf-8", errors="replace")

    result = {
        "product_name": _js_var(raw, "productName"),
        "firmware":     _js_var(raw, "webFirmwareVersion") or _js_var(raw, "FirmwareVersion") or _js_var(raw, "SoftwareVersion"),
        "hardware":     _js_var(raw, "HardwareVersion") or _js_var(raw, "webHardwareVersion"),
        "serial":       _js_var(raw, "SerialNumber") or _js_var(raw, "webSerialNumber"),
        "uptime":       _js_var(raw, "UpTime") or _js_var(raw, "DeviceUpTime"),
    }

    # Fallback productName desde wan_list_info.asp
    if not result["product_name"]:
        wli = _get(opener, f"{base}/html/bbsp/common/wan_list_info.asp").decode("utf-8", errors="replace")
        result["product_name"] = _js_var(wli, "productName")

    return result


# ---------------------------------------------------------------------------
# ONT State
# ---------------------------------------------------------------------------

def get_ont_state(opener, host: str) -> dict:
    base = f"http://{host}"
    raw = _get(opener, f"{base}/html/bbsp/common/ontstate.asp").decode("utf-8", errors="replace")

    pon_mode  = _js_var(raw, "PonMode")
    cfg_mode  = _js_var(raw, "CfgModeWord")
    gpon_args = _parse_constructor(raw, "OntStateInfo")
    ont_status = gpon_args[2] if len(gpon_args) > 2 else ""
    ont_id     = gpon_args[1] if len(gpon_args) > 1 else ""
    online     = ont_status.upper() in ("O5", "O5AUTH") if pon_mode.lower() == "gpon" else ont_status == "ONLINE"

    return {
        "pon_mode":   pon_mode.upper(),
        "cfg_mode":   cfg_mode,
        "ont_status": ont_status,
        "ont_id":     ont_id,
        "online":     online,
    }


# ---------------------------------------------------------------------------
# Optical Info
# ---------------------------------------------------------------------------

def get_optic_info(opener, host: str) -> dict:
    base = f"http://{host}"
    raw = _get(opener, f"{base}/html/amp/opticinfo/opticinfo.asp",
               referer=f"{base}/").decode("utf-8", errors="replace")

    # stOpticInfo(domain, status, TxPower, RxPower, Voltage_mV, Temp_C, TxCurrent_mA,
    #             ?, ?, Vendor, Serial, Date, TxWL_nm, RxWL_nm, Range_km, ?)
    a = _parse_constructor(raw, "stOpticInfo")
    link_time = _js_var(raw, "LinkTime")

    return {
        "status":      a[1]           if len(a) > 1  else "",
        "tx_power":    a[2].strip()   if len(a) > 2  else "",
        "rx_power":    a[3].strip()   if len(a) > 3  else "",
        "voltage":     a[4]           if len(a) > 4  else "",
        "temperature": a[5]           if len(a) > 5  else "",
        "tx_current":  a[6]           if len(a) > 6  else "",
        "vendor":      a[9].strip()   if len(a) > 9  else "",
        "serial":      a[10].strip()  if len(a) > 10 else "",
        "tx_wl":       a[12]          if len(a) > 12 else "",
        "rx_wl":       a[13]          if len(a) > 13 else "",
        "link_time":   link_time,
    }


# ---------------------------------------------------------------------------
# WAN
# ---------------------------------------------------------------------------

def _parse_wan_args(raw_args: str) -> list:
    return [_decode_js(m.group(1)) for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', raw_args)]


def get_wan_status(opener, host: str, token: str) -> dict:
    base = f"http://{host}"
    raw = _post(opener, f"{base}/html/bbsp/common/getwanlist.asp",
                data={"x.X_HW_Token": token},
                headers={"Referer": f"{base}/CustomApp/mainpage.asp"}).decode("utf-8", errors="replace")

    results = {"ip_wan": [], "ppp_wan": []}

    for m in re.finditer(r'new WanIP\(([^)]+)\)', raw):
        a = _parse_wan_args(m.group(1))
        if len(a) < 20:
            continue
        results["ip_wan"].append({
            "name": a[8], "status": a[5], "connection_status": a[12],
            "ip_address": a[15], "subnet_mask": a[16], "gateway": a[17],
            "dns": a[20], "vlan_id": a[21], "mac": a[4],
            "mode": a[13], "ip_mode": a[14], "nat": a[18],
            "remote_wan_info": a[7], "service_list": a[28] if len(a) > 28 else "",
            "uptime": a[43] if len(a) > 43 else "",
        })

    for m in re.finditer(r'new WanPPP\(([^)]+)\)', raw):
        a = _parse_wan_args(m.group(1))
        if len(a) < 14:
            continue
        results["ppp_wan"].append({
            "name": a[8], "status": a[5], "connection_status": a[12],
            "last_conn_err": a[6], "ip_address": a[14], "gateway": a[15],
            "dns": a[18], "username": a[19], "mac": a[4],
            "mode": a[13], "nat": a[16], "remote_wan_info": a[7],
            "service_list": a[26] if len(a) > 26 else "",
            "mtu": a[33] if len(a) > 33 else "",
            "isp": a[34] if len(a) > 34 else "",
            "uptime": a[40] if len(a) > 40 else "",
        })

    return results


# ---------------------------------------------------------------------------
# WAN Traffic Stats
# ---------------------------------------------------------------------------

def get_wan_stats(opener, host: str) -> dict:
    """
    WaninfoStats(domain, BytesSent, BytesReceived, PktsSent, PktsReceived,
                 UnicastSent, UnicastRecv, DiscardSent, DiscardRecv, ErrSent, ErrRecv)
    """
    base = f"http://{host}"
    stats = {}
    for key, path in [
        ("ip",  "/html/bbsp/common/get_wan_list_ipwanstat.asp"),
        ("ppp", "/html/bbsp/common/get_wan_list_pppwanstat.asp"),
    ]:
        raw = _get(opener, f"{base}{path}").decode("utf-8", errors="replace")
        stats[key] = []
        for a in _parse_all_constructors(raw, "WaninfoStats"):
            if len(a) < 3:
                continue
            stats[key].append({
                "bytes_sent":   a[1] if len(a) > 1 else "",
                "bytes_recv":   a[2] if len(a) > 2 else "",
                "pkts_sent":    a[3] if len(a) > 3 else "",
                "pkts_recv":    a[4] if len(a) > 4 else "",
                "discard_recv": a[8] if len(a) > 8 else "",
                "err_sent":     a[9] if len(a) > 9 else "",
                "err_recv":     a[10] if len(a) > 10 else "",
            })
    return stats


# ---------------------------------------------------------------------------
# ETH Ports
# ---------------------------------------------------------------------------

# GEInfo(domain, Enable, Speed_code, ?)
# LANStats(domain, TxPkts, TxErr, TxBytes, TxDiscard, TxUnk, TxMulti,
#          RxPkts, RxPktErr, RxBytes, RxBytesErr, RxDiscard, RxUnk)
# PONStats(domain, TxFrames, TxErr, TxDrop, TxUnk, RxFrames, RxErr, RxDrop)

_SPEED_MAP = {"0": "-", "1": "10", "2": "100", "3": "1000", "4": "2500", "5": "10000"}


def get_eth_info(opener, host: str) -> dict:
    base = f"http://{host}"
    raw = _get(opener, f"{base}/html/amp/ethinfo/ethinfo.asp",
               referer=f"{base}/").decode("utf-8", errors="replace")

    ge_ports  = _parse_all_constructors(raw, "GEInfo")
    lan_stats = _parse_all_constructors(raw, "LANStats")
    pon_args  = _parse_constructor(raw, "PONStats")

    ports = []
    for i, ge in enumerate(ge_ports):
        stat = lan_stats[i] if i < len(lan_stats) else []
        speed_code = ge[2] if len(ge) > 2 else "0"
        ports.append({
            "port":     f"LAN{i + 1}",
            "enabled":  ge[1] if len(ge) > 1 else "0",
            "speed":    _SPEED_MAP.get(speed_code, speed_code),
            "tx_bytes": stat[3]  if len(stat) > 3  else "",
            "rx_bytes": stat[9]  if len(stat) > 9  else "",
            "tx_pkts":  stat[1]  if len(stat) > 1  else "",
            "rx_pkts":  stat[7]  if len(stat) > 7  else "",
            "tx_err":   stat[2]  if len(stat) > 2  else "",
            "rx_err":   stat[8]  if len(stat) > 8  else "",
        })

    pon = {}
    if pon_args:
        pon = {
            "tx_frames": pon_args[1] if len(pon_args) > 1 else "",
            "tx_err":    pon_args[2] if len(pon_args) > 2 else "",
            "rx_frames": pon_args[5] if len(pon_args) > 5 else "",
            "rx_err":    pon_args[6] if len(pon_args) > 6 else "",
        }

    return {"ports": ports, "pon": pon}


# ---------------------------------------------------------------------------
# WLAN
# ---------------------------------------------------------------------------

def get_wlan_info(opener, host: str) -> dict:
    base = f"http://{host}"
    raw = _get(opener, f"{base}/html/amp/wlaninfo/wlaninfo.asp",
               referer=f"{base}/").decode("utf-8", errors="replace")

    enabled_2g = _js_var(raw, "wlanEnbl") != "0"
    enabled_5g = _js_var(raw, "radioEnable1") not in ("0", "")
    chip_2g    = _js_var(raw, "wlanChipType2G")
    chip_5g    = _js_var(raw, "wlanChipType5G")
    chan_info   = _js_var(raw, "ChanInfo")

    return {
        "enabled_2g": enabled_2g,
        "enabled_5g": enabled_5g,
        "chip_2g":    chip_2g,
        "chip_5g":    chip_5g,
        "chan_info":  chan_info,
    }


# ---------------------------------------------------------------------------
# LAN Clients
# ---------------------------------------------------------------------------

def get_lan_clients(opener, host: str, token: str) -> list:
    """
    DHCPInfo(domain, hostname, ip, mac, lease_remain_secs, devtype,
             interface_type, address_source, connected_time_secs)
    """
    base = f"http://{host}"
    raw = _post(opener, f"{base}/html/bbsp/common/GetLanUserDhcpInfo.asp",
                data={"x.X_HW_Token": token}).decode("utf-8", errors="replace")

    clients = []
    for m in re.finditer(r'new\s+DHCPInfo\s*\(([^)]+)\)', raw):
        a = [_decode_js(x.group(1)) for x in re.finditer(r'"((?:[^"\\]|\\.)*)"', m.group(1))]
        if len(a) < 4:
            continue
        clients.append({
            "hostname":       a[1] if len(a) > 1 else "",
            "ip":             a[2] if len(a) > 2 else "",
            "mac":            a[3] if len(a) > 3 else "",
            "lease_remain":   a[4] if len(a) > 4 else "",
            "interface":      a[6] if len(a) > 6 else "",
            "address_source": a[7] if len(a) > 7 else "",
            "connected_time": a[8] if len(a) > 8 else "",
        })
    return clients


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_uptime(seconds_str: str) -> str:
    try:
        secs = int(seconds_str)
    except (ValueError, TypeError):
        return "-"
    if secs <= 0:
        return "-"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)


def _fmt_bytes(b_str: str) -> str:
    try:
        b = int(b_str)
    except (ValueError, TypeError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


_STATUS_ICON = {
    "Connected": "🟢", "Disconnected": "🔴", "Connecting": "🟡", "Invalid": "⚫",
}
_SEP  = "=" * 64
_LINE = "─" * 64


def print_all(data: dict, as_json: bool = False):
    if as_json:
        print(_json.dumps(data, indent=2, ensure_ascii=False))
        return

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{_SEP}")
    print(f"  Router Status  —  {ts}")
    print(_SEP)

    # ── Device ──────────────────────────────────────────────────────────────
    d   = data.get("device", {})
    ont = data.get("ont", {})
    print(f"\n── DEVICE {'─'*55}")
    if d.get("product_name"):
        print(f"  Model       : {d['product_name']}")
    if d.get("firmware"):
        print(f"  Firmware    : {d['firmware']}")
    if d.get("hardware"):
        print(f"  Hardware    : {d['hardware']}")
    if d.get("serial"):
        print(f"  Serial      : {d['serial']}")
    if d.get("uptime"):
        print(f"  Uptime      : {_fmt_uptime(d['uptime'])}")
    if ont:
        icon = "🟢" if ont.get("online") else "🔴"
        print(f"  PON Mode    : {ont.get('pon_mode', '-')}  {icon} ONT {ont.get('ont_status', '-')}")
        if ont.get("cfg_mode"):
            print(f"  Config      : {ont['cfg_mode']}")

    # ── Optical ─────────────────────────────────────────────────────────────
    op = data.get("optic", {})
    if op:
        print(f"\n── OPTICAL {'─'*54}")
        status = op.get("status", "")
        icon   = "🟢" if status == "ok" else "🔴"
        print(f"  Status      : {icon} {status}")
        if op.get("tx_power") and op["tx_power"] != "--":
            print(f"  Tx Power    : {op['tx_power']} dBm")
        if op.get("rx_power") and op["rx_power"] != "--":
            print(f"  Rx Power    : {op['rx_power']} dBm")
        if op.get("temperature") and op["temperature"] != "--":
            print(f"  Temperature : {op['temperature']} °C")
        if op.get("voltage") and op["voltage"] != "--":
            v = op["voltage"]
            try:
                print(f"  Voltage     : {int(v)/1000:.2f} V")
            except ValueError:
                print(f"  Voltage     : {v} mV")
        if op.get("tx_current") and op["tx_current"] != "--":
            print(f"  Tx Current  : {op['tx_current']} mA")
        if op.get("vendor"):
            print(f"  Vendor      : {op['vendor']}")
        if op.get("serial"):
            print(f"  SFP Serial  : {op['serial']}")
        if op.get("tx_wl"):
            print(f"  Wavelength  : Tx {op['tx_wl']} nm / Rx {op.get('rx_wl', '-')} nm")
        if op.get("link_time"):
            print(f"  PON Uptime  : {_fmt_uptime(op['link_time'])}")

    # ── WAN ─────────────────────────────────────────────────────────────────
    wan       = data.get("wan", {})
    wan_stats = data.get("wan_stats", {})
    all_wans  = (
        [("IP WAN",  w, "ip")  for w in wan.get("ip_wan",  [])] +
        [("PPP WAN", w, "ppp") for w in wan.get("ppp_wan", [])]
    )
    if all_wans:
        print(f"\n── WAN {'─'*58}")
        for wtype, w, wkey in all_wans:
            status = w.get("status", "?")
            icon   = _STATUS_ICON.get(status, "❓")
            print(f"\n  [{wtype}] {w.get('name', '-')}  {icon} {status}")
            print(f"    Conn status : {w.get('connection_status', '-')}")
            if w.get("uptime"):
                print(f"    Duration    : {_fmt_uptime(w['uptime'])}")
            print(f"    IP address  : {w.get('ip_address', '-')}")
            if w.get("subnet_mask"):
                print(f"    Subnet mask : {w['subnet_mask']}")
            print(f"    Gateway     : {w.get('gateway', '-')}")
            print(f"    DNS         : {w.get('dns', '-')}")
            print(f"    MAC         : {w.get('mac', '-')}")
            if w.get("vlan_id"):
                print(f"    VLAN ID     : {w['vlan_id']}")
            if w.get("username"):
                print(f"    PPP User    : {w['username']}")
            if w.get("mtu") and w["mtu"] not in ("0", ""):
                print(f"    MTU         : {w['mtu']}")
            st_list = wan_stats.get(wkey, [])
            if st_list:
                st = st_list[0]
                tx = _fmt_bytes(st.get("bytes_sent", ""))
                rx = _fmt_bytes(st.get("bytes_recv", ""))
                if tx != "-" or rx != "-":
                    print(f"    Traffic     : ↑ {tx}  ↓ {rx}")
            if w.get("last_conn_err") and w["last_conn_err"] not in ("", "ERROR_NONE"):
                print(f"    ⚠ Last err  : {w['last_conn_err']}")

    # ── ETH Ports ───────────────────────────────────────────────────────────
    eth   = data.get("eth", {})
    ports = eth.get("ports", [])
    pon   = eth.get("pon", {})
    if ports:
        print(f"\n── ETH PORTS {'─'*52}")
        for p in ports:
            enabled = p.get("enabled", "0")
            speed   = p.get("speed", "")
            icon    = "🟢" if enabled == "1" else "⚫"
            speed_s = f"  {speed} Mbps" if speed and speed != "-" else ""
            print(f"  {p['port']}  {icon}{speed_s}")
            if enabled == "1":
                tx_b = _fmt_bytes(p.get("tx_bytes", ""))
                rx_b = _fmt_bytes(p.get("rx_bytes", ""))
                if tx_b != "-":
                    print(f"    Traffic : ↑ {tx_b}  ↓ {rx_b}")
        if pon:
            print(f"  PON  🟢")
            if pon.get("tx_frames"):
                print(f"    Tx frames : {int(pon['tx_frames']):,}  err: {pon.get('tx_err', 0)}")
                print(f"    Rx frames : {int(pon['rx_frames']):,}  err: {pon.get('rx_err', 0)}")

    # ── WLAN ────────────────────────────────────────────────────────────────
    wlan = data.get("wlan", {})
    if wlan:
        print(f"\n── WLAN {'─'*57}")
        i2g = "🟢 ON" if wlan.get("enabled_2g") else "⚫ OFF"
        i5g = "🟢 ON" if wlan.get("enabled_5g") else "⚫ OFF"
        print(f"  2.4 GHz : {i2g}")
        print(f"  5 GHz   : {i5g}")

    # ── LAN Clients ─────────────────────────────────────────────────────────
    clients = data.get("lan_clients", [])
    if clients:
        print(f"\n── LAN CLIENTS {'─'*50}")
        for c in clients:
            host_s = c.get("hostname", "--")
            ip_s   = c.get("ip", "--")
            mac_s  = c.get("mac", "--")
            iface  = c.get("interface", "-")
            conn_t = _fmt_uptime(c.get("connected_time", ""))
            lease  = _fmt_uptime(c.get("lease_remain", ""))
            print(f"  {host_s:<20s}  {ip_s:<17s}  {mac_s}  [{iface}]")
            if conn_t and conn_t != "-":
                print(f"    Connected : {conn_t}  |  Lease rem: {lease}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Estado completo del router Huawei EG8021V5")
    ap.add_argument("--host",  default="192.168.18.1")
    ap.add_argument("--user",  default="Epadmin")
    ap.add_argument("--pass",  dest="password", default="adminEp")
    ap.add_argument("--json",  action="store_true", help="Output JSON")
    ap.add_argument("--watch", type=int, metavar="SEG", help="Polling cada N segundos")
    args = ap.parse_args()

    print(f"Conectando a {args.host}...", file=sys.stderr)
    try:
        opener, token = login(args.host, args.user, args.password)
    except Exception as e:
        print(f"ERROR en login: {e}", file=sys.stderr)
        sys.exit(1)
    print("Login OK.", file=sys.stderr)

    def collect():
        return {
            "device":      get_device_info(opener, args.host),
            "ont":         get_ont_state(opener, args.host),
            "optic":       get_optic_info(opener, args.host),
            "wan":         get_wan_status(opener, args.host, token),
            "wan_stats":   get_wan_stats(opener, args.host),
            "eth":         get_eth_info(opener, args.host),
            "wlan":        get_wlan_info(opener, args.host),
            "lan_clients": get_lan_clients(opener, args.host, token),
        }

    if args.watch:
        while True:
            try:
                print_all(collect(), args.json)
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
            time.sleep(args.watch)
    else:
        try:
            print_all(collect(), args.json)
        except Exception as e:
            print(f"Error al obtener datos: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
