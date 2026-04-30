# routerstats

Python scripts and HTTP API to query live statistics and status from a **Huawei EG8021V5** ONT/GPON router via its web interface — no official API required.

Reverse-engineered from the router's ASP-based web UI. Uses only the Python standard library (no third-party dependencies).

---

## Features

| Component | What it does |
|---|---|
| `api_server.py` | HTTP API server (`GET /status`) — returns all router data as JSON. Runs in Docker. |
| `router_info.py` | Full dashboard: Device info, ONT/PON state, Optical (SFP) readings, WAN + traffic stats, ETH ports, WLAN state, LAN DHCP clients |
| `wan_status.py` | Focused WAN-only view: IP WAN / PPPoE status, IP address, gateway, DNS, uptime, errors |

### API server highlights

- **Persistent session** — logs in once at startup, reuses the session for all requests, re-authenticates automatically when it expires (every 5 min).
- **Smart caching** — static data (device info, WLAN config) cached 10 minutes; dynamic data (WAN, traffic stats, clients, optic, ETH, ONT) cached 30 seconds.
- **Auto-retry** — if a fetch fails (session killed by the router), invalidates the session and retries once with a fresh login.
- **Fast responses** — cached requests served in ~2-5 ms.

### CLI scripts

Both `router_info.py` and `wan_status.py` support:
- **Human-readable output** (default) with status icons
- **JSON output** via `--json`
- **Continuous polling** via `--watch N` (refresh every N seconds)

---

## Requirements

- Python 3.9+
- No external packages — uses only `urllib`, `http`, `re`, `argparse`, `base64`, `json` from the standard library
- Docker (optional, for running the API server)

---

## Supported hardware

| Model | Interface |
|---|---|
| Huawei EG8021V5 | HTTP ASP (port 80) |

The login flow and endpoint paths may also work on other Huawei HG/EG ONT models that share the same firmware UI (`/html/ssmp/`, `/html/bbsp/`, `/html/amp/`).

---

## Quick start — API server (Docker)

```bash
docker compose up -d
```

Then query the API:

```bash
curl http://localhost:8000/status
```

To customize credentials, edit `docker-compose.yml` or pass them on the command line:

```bash
docker compose run --rm router-api python api_server.py \
  --router-host 192.168.18.1 --user Epadmin --pass adminEp
```

### API server CLI arguments

| Argument | Default | Description |
|---|---|---|
| `--host` | `0.0.0.0` | Interface to bind to |
| `--port` | `8000` | Port to listen on |
| `--router-host` | `192.168.18.1` | Router IP address |
| `--user` | `Epadmin` | Web UI username |
| `--pass` | `adminEp` | Web UI password |

### API response example

```bash
curl -s http://localhost:8000/status | python3 -m json.tool
```

```json
{
  "device": {
    "product_name": "EG8021V5",
    "firmware": "V5R023C00S218",
    "hardware": "3ABD.A",
    "serial": "485754437F684FB4",
    "mac": "60:10:9E:80:C6:FC",
    "description": "EchoLife EG8021V5 GPON Terminal ...",
    "uptime": "278545"
  },
  "ont": { "pon_mode": "GPON", "ont_status": "O5", "online": true, "..." : "..." },
  "optic": { "status": "ok", "tx_power": "2.13", "rx_power": "-23.28", "..." : "..." },
  "wan": { "ip_wan": ["..."], "ppp_wan": ["..."] },
  "wan_stats": { "ip": ["..."], "ppp": ["..."] },
  "eth": { "ports": ["..."], "pon": {} },
  "wlan": { "enabled_2g": true, "enabled_5g": true, "..." : "..." },
  "lan_clients": [{ "hostname": "pc1", "ip": "192.168.18.10", "..." : "..." }]
}
```

### Cache behavior

| Data | TTL | Examples |
|---|---|---|
| Static | 10 min | Device info, WLAN config |
| Dynamic | 30 s | WAN status, traffic stats, optic readings, ETH ports, ONT state, LAN clients |
| Session | 5 min | Router login session — re-authenticates automatically |

---

## Usage — CLI scripts

### Full router status

```bash
python3 router_info.py
python3 router_info.py --host 192.168.18.1 --user Epadmin --pass adminEp
python3 router_info.py --json
python3 router_info.py --watch 30
```

### WAN status only

```bash
python3 wan_status.py
python3 wan_status.py --json
python3 wan_status.py --watch 10
```

### CLI arguments

| Argument | Default | Description |
|---|---|---|
| `--host` | `192.168.18.1` | Router IP address |
| `--user` | `Epadmin` | Web UI username |
| `--pass` | `adminEp` | Web UI password (sent as Base64, matching browser behavior) |
| `--json` | off | Print raw JSON instead of formatted text |
| `--watch N` | off | Poll every N seconds indefinitely |

---

## Project structure

```
api_server.py          # HTTP API server (GET /status) with session management and caching
router_info.py         # Core library: login, data fetching, parsing, and CLI dashboard
wan_status.py          # WAN-only CLI (imports from router_info.py)
tests/
  test_api_server.py   # Unit tests for the API server (17 tests)
Dockerfile             # Docker image definition
docker-compose.yml     # Docker Compose service configuration
.dockerignore          # Excludes .venv, tests, docs from Docker build
requirements.txt       # Python dependencies (stdlib only)
```

---

## How it works

The router's web UI is ASP-based and uses JavaScript constructors in its responses (e.g. `new stDeviceInfo(...)`, `new WanPPP(...)`, `new GEInfo(...)`) to pass data to the browser. These scripts reverse-engineer that flow:

1. **Pre-login token** — `GET /html/ssmp/common/getRandString.asp`
2. **Login** — `POST /login.cgi` with username and Base64-encoded password
3. **Session token** — `GET /html/ssmp/common/GetRandToken.asp`
4. **Data endpoints** — Various `POST`/`GET` to `/html/bbsp/` and `/html/amp/` ASP pages, passing `x.X_HW_Token` as a CSRF token
5. **Parsing** — Regex extraction of JS constructor arguments from the raw HTML/JS responses

The API server (`api_server.py`) wraps this flow in a persistent session that survives across HTTP requests, avoiding the full login circuit on every query.

---

## Security note

Credentials are transmitted over plain HTTP (port 80) as the router does not support HTTPS. Avoid exposing the router's management interface to untrusted networks.

---

## License

MIT
