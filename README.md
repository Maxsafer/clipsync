# clipsync

A single-user, self-hosted clipboard relay. Push/pull text, images, and files
between your devices via a web UI or a REST API. The killer use case is
`curl`-ing your clipboard into an SSH session.

- One Docker container, SQLite + a `/data` volume — that's the whole deployment.
- Web UI (vanilla JS, dark/light themes) and a curl-friendly API.
- SSE live updates: paste on one device, it appears in another tab without
  refreshing.

---

## Quick start

From the project root:

```bash
# Generate .env with a real random SECRET_KEY in one shot
sed "s|^CLIPSYNC_SECRET_KEY=.*|CLIPSYNC_SECRET_KEY=$(openssl rand -hex 32)|" \
    .env.example > .env

# Edit CLIPSYNC_USERNAME and CLIPSYNC_PASSWORD before the first start
$EDITOR .env

docker compose up -d --build
open http://localhost:8080   # or your-host:8080
```

After first boot, sign in with the username/password you set, then grab your
API token from the Settings tab.

> The `sed` step is required because plain `cp .env.example .env` leaves
> `CLIPSYNC_SECRET_KEY=` empty and the container won't start. If you'd rather
> hand-edit, run `openssl rand -hex 32` separately and paste the output as the
> value — do **not** write `CLIPSYNC_SECRET_KEY=$(openssl rand -hex 32)` into
> `.env` by hand, since `.env` files don't evaluate shell substitutions.

## Environment variables

| Variable               | Required        | Notes                                              |
|------------------------|-----------------|----------------------------------------------------|
| `CLIPSYNC_SECRET_KEY`  | always          | Signs session cookies. Keep stable across restarts. |
| `CLIPSYNC_USERNAME`    | first run only  | Bootstrap username.                                |
| `CLIPSYNC_PASSWORD`    | first run only  | Bootstrap password. **Hashed into the DB on first start and ignored on subsequent runs.** Change it from the Settings tab afterwards. |
| `CLIPSYNC_DATA_DIR`    | no (default `/data`) | Where the SQLite DB and blobs live.           |
| `CLIPSYNC_PORT`        | no (default 8080)    | Listen port. The compose file uses this for both the host-side mapping and the in-container listener, so a single value covers both. |

You can leave `CLIPSYNC_PASSWORD` set in your env forever — it's still ignored
after the first run.

## Operating it

### Change the port

Edit `CLIPSYNC_PORT` in `.env`, then:

```bash
docker compose up -d
```

Compose detects the config change and recreates the container automatically.
The single value drives both the host-side mapping and the in-container
listener, so 8085 in `.env` → reachable at `http://your-host:8085`. No
`docker rm`, no rebuild required.

### Change the password

You're logged in and know the current password → **Settings tab → Change
password**. Takes effect immediately, no restart.

### Reset a forgotten password

The password lives in `./data/clipsync.db`, not in `.env`. To re-bootstrap
from `.env`:

```bash
docker compose down
sudo rm -rf data           # also wipes clips and rotates the API token
docker compose up -d
```

This is the destructive option — only use it if you've genuinely lost access.
Routine password changes should go through the Settings tab.

### Rotate the API token

**Settings tab → API token → Regenerate**. The old token is invalidated
immediately.

### Change the username

The username only matters at the login screen; it isn't editable in the UI
today. If you really need to change it, follow the "Reset a forgotten
password" steps above with a new `CLIPSYNC_USERNAME` in `.env`.

## API

All endpoints require auth. You can authenticate with:

- A signed session cookie (browser).
- `Authorization: Bearer <token>` header.
- `?token=<token>` query parameter (convenient for curl).

Two optional headers shape how clips are stored:

- **`X-Device-Label: <name>`** — tag the clip with where it came from
  (`laptop`, `phone`, `$(hostname)`, …). Shows up in the UI as "from <name>"
  and on `GET /api/clips`. Falls back to a short hash of the User-Agent if
  omitted.
- **`X-Filename: <name>`** — only meaningful when pushing raw bytes (not
  multipart). Sets the download filename. Multipart `-F file=@…` carries the
  filename automatically, so you don't need this there.

### Push

```bash
TOKEN=...   # from the Settings tab

# Text from stdin
echo "hello from $(hostname)" | curl \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: text/plain" \
  -H "X-Device-Label: $(hostname)" \
  --data-binary @- \
  http://your-host:8080/api/clip

# A file (multipart — filename preserved automatically)
curl -H "Authorization: Bearer $TOKEN" \
     -H "X-Device-Label: $(hostname)" \
     -F "file=@/path/to/file.zip" \
     http://your-host:8080/api/clip

# Raw bytes with explicit filename
curl -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/octet-stream" \
     -H "X-Filename: notes.bin" \
     --data-binary @notes.bin \
     http://your-host:8080/api/clip

# An image (raw)
curl -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: image/png" \
     --data-binary @screenshot.png \
     http://your-host:8080/api/clip
```

### Pull

```bash
# Latest clip's raw bytes with the original Content-Type
curl -H "Authorization: Bearer $TOKEN" http://your-host:8080/api/clip/latest

# Latest clip forced as text/plain (errors if latest isn't text)
curl -H "Authorization: Bearer $TOKEN" http://your-host:8080/api/clip/latest.txt

# Latest as application/octet-stream
curl -H "Authorization: Bearer $TOKEN" http://your-host:8080/api/clip/latest.bin

# Metadata list
curl -H "Authorization: Bearer $TOKEN" http://your-host:8080/api/clips?limit=20

# A specific clip
curl -H "Authorization: Bearer $TOKEN" http://your-host:8080/api/clip/<id>
curl -H "Authorization: Bearer $TOKEN" http://your-host:8080/api/clip/<id>/meta
```

### Manage

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" http://your-host:8080/api/clip/<id>
curl -X DELETE -H "Authorization: Bearer $TOKEN" http://your-host:8080/api/clips   # clear all
curl -N        -H "Authorization: Bearer $TOKEN" http://your-host:8080/api/events  # SSE stream
```

The SSE stream emits three event types, JSON payload after each:

| Event           | Payload                                  |
|-----------------|------------------------------------------|
| `clip.new`      | full clip metadata (same shape as `/api/clips` items) |
| `clip.deleted`  | `{ "id": "<clip-id>" }`                  |
| `clips.cleared` | `{ "count": <number-deleted> }`          |

A `:heartbeat` comment line is sent every ~15 seconds to keep proxies from
closing the connection.

### Auth

```bash
# Log in (browser-style — sets a session cookie)
curl -c cookies.txt -H "Content-Type: application/json" \
     -d '{"username":"alice","password":"...","remember":true}' \
     http://your-host:8080/api/auth/login

# Check current session
curl -b cookies.txt http://your-host:8080/api/auth/me           # { authed, username } or 401
curl -b cookies.txt http://your-host:8080/api/auth/token        # { api_token }

# Mutate
curl -b cookies.txt -X POST http://your-host:8080/api/auth/logout
curl -b cookies.txt -X POST http://your-host:8080/api/auth/rotate-token
curl -b cookies.txt -X POST -H "Content-Type: application/json" \
     -d '{"current":"old","new":"newpassword"}' \
     http://your-host:8080/api/auth/change-password
```

`rotate-token`, `change-password`, and `token` also accept Bearer auth, so you
can drive them from scripts without a session.

### Settings

`GET /api/settings` returns:

```json
{ "history_size": 50, "item_ttl_hours": 24, "max_item_size_mb": 100 }
```

`POST /api/settings` accepts partial updates. `item_ttl_hours: 0` disables
expiry; `max_item_size_mb: 0` disables the size cap.

## Security notes

- **`?token=...` lands in reverse-proxy logs and shell history.** It exists
  because some curl patterns are easier that way. Prefer the `Authorization`
  header for anything sensitive or anything you don't fully control.
- **The API token is stored in cleartext** in the SQLite DB so the Settings tab
  can show it for copy/paste. Single-user, single-host design — protect `/data`
  the same way you'd protect a `.env`.
- **Put HTTPS in front.** The container speaks plain HTTP. Use Caddy,
  Tailscale Serve, or a similar terminator — see below.

## Reverse proxy / HTTPS

The container only speaks plain HTTP. Put a TLS terminator in front for
anything beyond your LAN. The SSE endpoint already sets
`Cache-Control: no-cache` and `X-Accel-Buffering: no`, so any reasonable proxy
(Nginx, Caddy, Traefik, Cloudflare Tunnel, Tailscale Serve) streams events
correctly without extra config.

Replace `8080` below with whatever `CLIPSYNC_PORT` you set.

**Caddy:**

```caddy
clips.example.com {
    reverse_proxy localhost:8080 {
        flush_interval -1   # SSE: don't buffer
    }
}
```

**Tailscale (no domain needed, picks up your tailnet cert):**

```bash
tailscale serve --bg --https=443 http://localhost:8080
```

**Nginx (snippet):**

```nginx
location / {
    proxy_pass         http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_buffering    off;            # SSE
    proxy_read_timeout 1h;             # SSE
    proxy_set_header   Host             $host;
    proxy_set_header   X-Forwarded-For  $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
}
```

## Image clipboard caveats

The web UI uses `navigator.clipboard.write` with `ClipboardItem` to copy
images to your system clipboard. That API is only available in **secure
contexts** (HTTPS or `localhost`), and **Firefox can't write images to the
clipboard yet**. When the API isn't available, the copy button falls back to
downloading the file instead.

Practical guidance:

- **On HTTPS** (any reverse proxy above): everything works — Chrome, Edge,
  Safari can copy images via the button. Firefox copies text but downloads
  images.
- **On plain HTTP**: text copy still works (via a legacy fallback). For
  images, the UI shows a hint reminding you that you can **right-click the
  image thumbnail and pick "Copy image"** — that browser-native action works
  on any origin, no clipboard API required.
- **Hosting on `http://localhost`** counts as a secure context too, so local
  development gets the full experience.

## Backup and upgrades

Everything stateful lives in `./data` (SQLite + blob files). Back it up with
a plain `tar`:

```bash
docker compose down
tar -czf clipsync-backup-$(date +%F).tgz data
docker compose up -d
```

To upgrade after a `git pull`:

```bash
docker compose up -d --build
```

Settings, password, API token, and clips all persist across rebuilds.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
CLIPSYNC_SECRET_KEY=dev CLIPSYNC_USERNAME=alice CLIPSYNC_PASSWORD=alice1234 \
  CLIPSYNC_DATA_DIR=./data \
  .venv/bin/python -m flask --app app run --port 8080 --debug
.venv/bin/pytest
```

## Layout

```
clipsync/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── app/
│   ├── __init__.py          # Flask app factory + TTL daemon
│   ├── config.py            # env + settings defaults
│   ├── db.py                # SQLite schema + helpers
│   ├── storage.py           # blob read/write
│   ├── auth.py              # session, bearer, query token
│   ├── clips.py             # /api/clip* + /api/events
│   ├── settings.py          # /api/settings
│   ├── events.py            # SSE pubsub broker
│   └── static/              # vanilla JS web UI
└── tests/
```

## What's not in here (intentionally)

Pinning, favorites, search, multi-user, sharing, WebSockets, migrations.
