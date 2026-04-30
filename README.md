# routerstats

Python scripts to query live statistics and status from a **Huawei EG8021V5** ONT/GPON router via its web interface — no official API required.

Reverse-engineered from the router's ASP-based web UI. Uses only the Python standard library (no third-party dependencies).

---

## Features

| Script | What it shows |
|---|---|
| `router_info.py` | Full dashboard: Device info, ONT/PON state, Optical (SFP) readings, WAN + traffic stats, ETH ports, WLAN state, LAN DHCP clients |
| `wan_status.py` | Focused WAN-only view: IP WAN / PPPoE status, IP address, gateway, DNS, uptime, errors |

Both scripts support:
- **Human-readable output** (default) with status icons
- **JSON output** via `--json`
- **Continuous polling** via `--watch N` (refresh every N seconds)

---

## Requirements

- Python 3.9+
- No external packages — uses only `urllib`, `http`, `re`, `argparse`, `base64`, `json` from the standard library

---

## Supported hardware

| Model | Interface |
|---|---|
| Huawei EG8021V5 | HTTP ASP (port 80) |

The login flow and endpoint paths may also work on other Huawei HG/EG ONT models that share the same firmware UI (`/html/ssmp/`, `/html/bbsp/`, `/html/amp/`).

---

## Usage

### Full router status

```bash
python3 router_info.py
```

With explicit credentials:

```bash
python3 router_info.py --host 192.168.18.1 --user Epadmin --pass adminEp
```

JSON output:

```bash
python3 router_info.py --json
```

Continuous polling every 30 seconds:

```bash
python3 router_info.py --watch 30
```

### WAN status only

```bash
python3 wan_status.py
python3 wan_status.py --host 192.168.18.1 --user Epadmin --pass adminEp
python3 wan_status.py --json
python3 wan_status.py --watch 10
```

---

## CLI arguments

| Argument | Default | Description |
|---|---|---|
| `--host` | `192.168.18.1` | Router IP address |
| `--user` | `Epadmin` | Web UI username |
| `--pass` | `adminEp` | Web UI password (sent as Base64, matching browser behavior) |
| `--json` | off | Print raw JSON instead of formatted text |
| `--watch N` | off | Poll every N seconds indefinitely |

---

## Sample output (`router_info.py`)

```
================================================================
  Router Status  —  2026-04-30 14:22:05
================================================================

── DEVICE ───────────────────────────────────────────────────────
  Model       : EG8021V5
  Firmware    : V300R019C10SPC130
  Serial      : HWTC1234ABCD
  Uptime      : 12d 4h 37m
  PON Mode    : GPON  🟢 ONT O5

── OPTICAL ──────────────────────────────────────────────────────
  Status      : 🟢 ok
  Tx Power    : 2.34 dBm
  Rx Power    : -18.50 dBm
  Temperature : 47 °C
  Voltage     : 3.27 V
  Vendor      : HWTC
  PON Uptime  : 12d 4h 35m

── WAN ──────────────────────────────────────────────────────────

  [PPP WAN] INTERNET_PPP  🟢 Connected
    Conn status : Connected
    Duration    : 4h 12m
    IP address  : 200.x.x.x
    Gateway     : 200.x.x.1
    DNS         : 8.8.8.8,8.8.4.4
    MAC         : AA:BB:CC:DD:EE:FF
    Traffic     : ↑ 1.2 GB  ↓ 8.7 GB

── ETH PORTS ────────────────────────────────────────────────────
  LAN1  🟢  1000 Mbps
    Traffic : ↑ 8.5 GB  ↓ 1.1 GB
  LAN2  ⚫
  LAN3  ⚫
  LAN4  ⚫
  PON  🟢
    Tx frames : 12,345,678  err: 0
    Rx frames : 98,765,432  err: 0

── WLAN ─────────────────────────────────────────────────────────
  2.4 GHz : 🟢 ON
  5 GHz   : 🟢 ON

── LAN CLIENTS ──────────────────────────────────────────────────
  my-laptop             192.168.18.10     AA:BB:CC:11:22:33  [ETH]
    Connected : 3h 41m  |  Lease rem: 20h 18m
```

---

## How it works

The router's web UI is ASP-based and uses JavaScript constructors in its responses (e.g. `new WanPPP(...)`, `new GEInfo(...)`) to pass data to the browser. These scripts reverse-engineer that flow:

1. **Pre-login token** — `GET /html/ssmp/common/getRandString.asp`
2. **Login** — `POST /login.cgi` with username and Base64-encoded password
3. **Session token** — `GET /html/ssmp/common/GetRandToken.asp`
4. **Data endpoints** — Various `POST`/`GET` to `/html/bbsp/` and `/html/amp/` ASP pages, passing `x.X_HW_Token` as a CSRF token
5. **Parsing** — Regex extraction of JS constructor arguments from the raw HTML/JS responses

No credentials are stored on disk; they are passed on the command line or use the built-in defaults.

---

## Security note

Credentials are transmitted over plain HTTP (port 80) as the router does not support HTTPS. Avoid exposing the router's management interface to untrusted networks.

---

## License

MIT
