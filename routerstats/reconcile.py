#!/usr/bin/env python3
"""reconcile.py - Mantiene declarativa la config del router Huawei EG8021V5

Cada boot, la OLT reaplica su propia config y pisa lo que hayas cambiado a
mano (WiFi, reserva DHCP, DMZ). Este script chequea el estado actual contra
un estado deseado y reaplica lo que haga falta.

Uso:
    python3 -m routerstats.reconcile                 # una sola pasada (para cron)
    python3 -m routerstats.reconcile --watch 60       # daemon, chequea cada 60s
    python3 -m routerstats.reconcile --dhcp-mac 08:55:31:A7:C7:F5 --dhcp-ip 192.168.18.2 --dmz-ip 192.168.18.2
"""

import argparse
import sys
import time
from urllib.error import URLError

from .router_info import login, get_wlan_info
from .router_config import reconcile_once, DEFAULT_WAN_DMZ_DOMAIN


def build_desired(args) -> dict:
    return {
        "wifi_2g_enabled": args.wifi_enabled,
        "wifi_5g_enabled": args.wifi_enabled,
        "dhcp_mac": args.dhcp_mac,
        "dhcp_ip": args.dhcp_ip,
        "dmz_ip": args.dmz_ip,
        "wan_dmz_domain": args.wan_dmz_domain,
    }


def main():
    ap = argparse.ArgumentParser(description="Reconciliador declarativo del router Huawei EG8021V5")
    ap.add_argument("--host", default="192.168.18.1")
    ap.add_argument("--user", default="Epadmin")
    ap.add_argument("--pass", dest="password", default="adminEp")

    ap.add_argument("--wifi-enabled", action=argparse.BooleanOptionalAction, default=False,
                     help="Estado deseado del WiFi (2.4G y 5G). Default: apagado.")
    ap.add_argument("--dhcp-mac", default="08:55:31:A7:C7:F5", help="MAC a reservar por DHCP")
    ap.add_argument("--dhcp-ip", default="192.168.18.2", help="IP a reservar para esa MAC")
    ap.add_argument("--dmz-ip", default="192.168.18.2", help="IP destino del mapeo DMZ")
    ap.add_argument("--wan-dmz-domain", default=DEFAULT_WAN_DMZ_DOMAIN,
                     help="Domain TR-069 de la conexión WAN sobre la que aplicar el DMZ")

    ap.add_argument("--watch", type=int, metavar="SEG", help="Chequeo continuo cada N segundos")
    args = ap.parse_args()

    desired = build_desired(args)

    print(f"Conectando a {args.host}...", file=sys.stderr)
    try:
        opener, token = login(args.host, args.user, args.password)
    except Exception as e:
        print(f"ERROR en login: {e}", file=sys.stderr)
        sys.exit(1)
    print("Login OK.", file=sys.stderr)

    def run_once():
        actions = reconcile_once(opener, args.host, token, desired, get_wlan_info)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        if actions:
            print(f"[{ts}] drift detectado, reaplicando:")
            for a in actions:
                print(f"  - {a}")
        else:
            print(f"[{ts}] sin drift, config OK")

    if args.watch:
        while True:
            try:
                run_once()
            except URLError as e:
                print(f"[{time.strftime('%H:%M:%S')}] Error de red: {e}", file=sys.stderr)
                try:
                    opener, token = login(args.host, args.user, args.password)
                except Exception:
                    pass
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Error: {e}", file=sys.stderr)
            time.sleep(args.watch)
    else:
        try:
            run_once()
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
