#!/usr/bin/env python3
"""
wan_status.py - Login al router Huawei EG8021V5 y recupera estado WAN

Uso:
    python3 wan_status.py
    python3 wan_status.py --host 192.168.18.1 --user Epadmin --pass adminEp
    python3 wan_status.py --json        # output JSON crudo
    python3 wan_status.py --watch 10    # polling cada 10 segundos

Flujo reverse-engineered del HAR:
  1. POST /asp/GetRandCount.asp  -> genera sesión (sin cookie, sin body)
  2. POST /login.cgi             -> user + password en base64 + X_HW_Token del HTML
     El token para el login se obtiene parseando el campo hidden 'onttoken' de GET /
  3. GET  /index.asp             -> el HTML contiene nuevo 'onttoken' para llamadas post-login
  4. POST /html/bbsp/common/getwanlist.asp  con x.X_HW_Token=<onttoken>
"""

import argparse
import base64
import re
import sys
import time
import json as _json
from html.parser import HTMLParser
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import URLError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TokenParser(HTMLParser):
    """Extrae el value del input hidden id='onttoken'."""
    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            attrs = dict(attrs)
            if attrs.get("id") == "onttoken":
                self.token = attrs.get("value")


def _post(session_opener, url, data: Optional[dict] = None, headers: Optional[dict] = None) -> bytes:
    body = urlencode(data).encode() if data else b""
    hdrs = {
        "User-Agent": "Mozilla/5.0 (wan_status.py)",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
    }
    if headers:
        hdrs.update(headers)
    req = Request(url, data=body, headers=hdrs, method="POST")
    with session_opener.open(req, timeout=10) as r:
        return r.read()


def _get(session_opener, url, referer: str = "") -> bytes:
    hdrs = {"User-Agent": "Mozilla/5.0 (wan_status.py)"}
    if referer:
        hdrs["Referer"] = referer
    req = Request(url, headers=hdrs)
    with session_opener.open(req, timeout=10) as r:
        return r.read()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login(host: str, username: str, password: str):
    """
    Devuelve (opener, token) donde:
      - opener: urllib opener con cookie jar (sesión activa)
      - token: X_HW_Token para usar en llamadas POST posteriores
    """
    from urllib.request import build_opener, HTTPCookieProcessor
    from http.cookiejar import CookieJar

    base = f"http://{host}"
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))

    # Paso 1: Obtener token pre-login desde el endpoint real
    pre_login_token = _get(opener, f"{base}/html/ssmp/common/getRandString.asp").decode("utf-8", errors="replace").strip()
    if not pre_login_token:
        raise RuntimeError("No se pudo obtener el token pre-login. ¿El router está accesible?")

    # Contraseña en base64 (así lo hace el browser)
    pw_b64 = base64.b64encode(password.encode()).decode()

    # Paso 2: Login
    _post(opener, f"{base}/login.cgi", data={
        "UserName": username,
        "PassWord": pw_b64,
        "Language": "english",
        "x.X_HW_Token": pre_login_token,
    }, headers={"Referer": f"{base}/"})

    # Paso 3: Obtener token post-login (sesión activa)
    session_token = _get(opener, f"{base}/html/ssmp/common/GetRandToken.asp").decode("utf-8", errors="replace").strip()
    if not session_token or "<html" in session_token.lower():
        raise RuntimeError(
            "Login fallido o token post-login no encontrado. "
            "Verificá usuario/contraseña."
        )

    return opener, session_token


# ---------------------------------------------------------------------------
# Parseo de getwanlist
# ---------------------------------------------------------------------------

def _decode_js_string(s: str) -> str:
    """Convierte escapes \\x3a -> : etc. del JS response."""
    return s.encode().decode("unicode_escape")


def _parse_wan_args(raw: str) -> list[str]:
    """Extrae los argumentos string de un constructor JS tipo new WanXxx("a","b",...)."""
    args = []
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', raw):
        args.append(_decode_js_string(m.group(1)))
    return args


def parse_getwanlist(body: str) -> dict:
    """
    Parsea el response JS de getwanlist.asp y devuelve un dict con la info WAN.
    Basado en los campos observados en el HAR:
      WanIP:  domain, X_HW_VXLAN, X_HW_OperateDisable, ConnectionTrigger, MACAddress,
              Status, LastConnErr, RemoteWanInfo, Name, Enable, ...,
              ConnectionStatus, Mode, IPMode, IPAddress, SubnetMask, Gateway,
              NATEnable, X_HW_NatType, DNS, VlanId, ...
      WanPPP: domain, ..., MACAddress, Status, LastConnErr, RemoteWanInfo, Name,
              ..., ConnectionStatus, Mode, ExternalIPAddress, RemoteIPAddress,
              NATEnable, ..., DNS, Username, Password(masked), ...
    """
    results = {"ip_wan": [], "ppp_wan": []}

    # --- IP WAN ---
    for m in re.finditer(r'new WanIP\(([^)]+)\)', body):
        args = _parse_wan_args(m.group(1))
        if len(args) < 20:
            continue
        results["ip_wan"].append({
            "name":              args[8] if len(args) > 8 else "",
            "status":            args[5] if len(args) > 5 else "",
            "connection_status": args[12] if len(args) > 12 else "",
            "ip_address":        args[15] if len(args) > 15 else "",
            "subnet_mask":       args[16] if len(args) > 16 else "",
            "gateway":           args[17] if len(args) > 17 else "",
            "dns":               args[20] if len(args) > 20 else "",
            "vlan_id":           args[21] if len(args) > 21 else "",
            "service_list":      args[28] if len(args) > 28 else "",
            "mac":               args[4]  if len(args) > 4  else "",
            "mode":              args[13] if len(args) > 13 else "",
            "ip_mode":           args[14] if len(args) > 14 else "",
            "nat":               args[18] if len(args) > 18 else "",
            "remote_wan_info":   args[7]  if len(args) > 7  else "",
            "uptime":            args[43] if len(args) > 43 else "",
        })

    # --- PPP WAN ---
    for m in re.finditer(r'new WanPPP\(([^)]+)\)', body):
        args = _parse_wan_args(m.group(1))
        if len(args) < 14:
            continue
        results["ppp_wan"].append({
            "name":              args[8]  if len(args) > 8  else "",
            "status":            args[5]  if len(args) > 5  else "",
            "connection_status": args[12] if len(args) > 12 else "",
            "last_conn_err":     args[6]  if len(args) > 6  else "",
            "ip_address":        args[14] if len(args) > 14 else "",  # ExternalIPAddress PPPoE
            "gateway":           args[15] if len(args) > 15 else "",
            "dns":               args[18] if len(args) > 18 else "",
            "username":          args[19] if len(args) > 19 else "",
            "service_list":      args[26] if len(args) > 26 else "",
            "mac":               args[4]  if len(args) > 4  else "",
            "mode":              args[13] if len(args) > 13 else "",
            "nat":               args[16] if len(args) > 16 else "",
            "remote_wan_info":   args[7]  if len(args) > 7  else "",
            "mtu":               args[33] if len(args) > 33 else "",
            "isp":               args[34] if len(args) > 34 else "",
            "uptime":            args[40] if len(args) > 40 else "",
        })

    return results


# ---------------------------------------------------------------------------
# Consulta WAN
# ---------------------------------------------------------------------------

def get_wan_status(opener, host: str, token: str) -> dict:
    base = f"http://{host}"
    body = _post(opener, f"{base}/html/bbsp/common/getwanlist.asp",
                 data={"x.X_HW_Token": token},
                 headers={"Referer": f"{base}/CustomApp/mainpage.asp"})
    raw = body.decode("utf-8", errors="replace")
    return parse_getwanlist(raw)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _fmt_uptime(seconds_str: str) -> str:
    """Convierte segundos a string legible como '2d 22h 38m'."""
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


STATUS_ICON = {
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
        icon = STATUS_ICON.get(status, "❓")
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
        if w.get('mtu'):
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
                # Re-login si hay error
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
