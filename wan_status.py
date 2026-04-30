#!/usr/bin/env python3
"""
wan_status.py - Vista WAN del router Huawei EG8021V5

Uso:
    python3 wan_status.py
    python3 wan_status.py --host 192.168.18.1 --user Epadmin --pass adminEp
    python3 wan_status.py --json
    python3 wan_status.py --watch 10
"""

import argparse
import json as _json
import sys
import time
from urllib.error import URLError

from router_info import login, get_wan_status


# ---------------------------------------------------------------------------
# Display
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


_STATUS_ICON = {
    "Connected": "🟢",
    "Disconnected": "🔴",
    "Connecting": "🟡",
    "Invalid": "⚫",
}


def print_wan_status(data: dict, as_json: bool = False):
    if as_json:
        print(_json.dumps(data, indent=2, ensure_ascii=False))
        return

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"  Estado WAN — {ts}")
    print(f"{'='*60}")

    all_wans = (
        [("IP WAN", w) for w in data["ip_wan"]] +
        [("PPP WAN", w) for w in data["ppp_wan"]]
    )

    if not all_wans:
        print("  (sin interfaces WAN detectadas)")
        return

    for wtype, w in all_wans:
        status = w.get("status", "?")
        icon = _STATUS_ICON.get(status, "❓")
        print(f"\n  [{wtype}] {w.get('name', '(sin nombre)')}  {icon} {status}")
        print(f"    Conn status : {w.get('connection_status', '-')}")
        if w.get('uptime'):
            print(f"    Duration    : {_fmt_uptime(w.get('uptime'))}")
        print(f"    IP address  : {w.get('ip_address', '-')}")
        if w.get('subnet_mask'):
            print(f"    Subnet mask : {w.get('subnet_mask', '-')}")
        print(f"    Gateway     : {w.get('gateway', '-')}")
        print(f"    DNS         : {w.get('dns', '-')}")
        print(f"    MAC         : {w.get('mac', '-')}")
        print(f"    Modo        : {w.get('mode', '-')} / {w.get('ip_mode', w.get('nat', '-'))}")
        if w.get('vlan_id'):
            print(f"    VLAN ID     : {w.get('vlan_id')}")
        if w.get('username'):
            print(f"    Usuario PPP : {w.get('username')}")
        if w.get('isp'):
            print(f"    ISP         : {w.get('isp')}")
        if w.get('mtu') and w['mtu'] not in ('0', ''):
            print(f"    MTU         : {w.get('mtu')}")
        if w.get('last_conn_err') and w.get('last_conn_err') not in ('', 'ERROR_NONE'):
            print(f"    ⚠ Último error: {w.get('last_conn_err')}")
        if w.get('service_list'):
            print(f"    Servicio    : {w.get('service_list')}")
        if w.get('remote_wan_info'):
            print(f"    Remote WAN  : {w.get('remote_wan_info')}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Consulta el estado WAN del router Huawei EG8021V5"
    )
    ap.add_argument("--host", default="192.168.18.1", help="IP del router (default: 192.168.18.1)")
    ap.add_argument("--user", default="Epadmin", help="Usuario del router")
    ap.add_argument("--pass", dest="password", default="adminEp",
                    help="Contraseña (texto plano, se envía en base64 como lo hace el browser)")
    ap.add_argument("--json", action="store_true", help="Output en JSON")
    ap.add_argument("--watch", type=int, metavar="SEGUNDOS",
                    help="Polling continuo cada N segundos")
    args = ap.parse_args()

    print(f"Conectando a {args.host}...", file=sys.stderr)
    try:
        opener, token = login(args.host, args.user, args.password)
    except Exception as e:
        print(f"ERROR en login: {e}", file=sys.stderr)
        sys.exit(1)

    print("Login OK.", file=sys.stderr)

    if args.watch:
        while True:
            try:
                data = get_wan_status(opener, args.host, token)
                print_wan_status(data, as_json=args.json)
            except URLError as e:
                print(f"[{time.strftime('%H:%M:%S')}] Error de red: {e}", file=sys.stderr)
                try:
                    opener, token = login(args.host, args.user, args.password)
                except Exception:
                    pass
            time.sleep(args.watch)
    else:
        try:
            data = get_wan_status(opener, args.host, token)
            print_wan_status(data, as_json=args.json)
        except Exception as e:
            print(f"ERROR consultando WAN: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
