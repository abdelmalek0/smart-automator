# Smart Automator — VPS deploy

Public entry: **http://156.67.83.177:6500** (include `:6500` — bare `http://156.67.83.177` is Chatwoot on 80/443)

| Port | Role |
|------|------|
| 6500 | Nginx — static UI + reverse proxy (must be open in UFW) |
| 6501 | uvicorn API (`127.0.0.1` only) |

## Firewall

UFW must allow inbound **6500/tcp** or browsers will hang on a white page:

```bash
sudo ufw allow 6500/tcp comment 'smart-automator'
```

`deploy/install.sh` does this automatically when UFW is installed.

## Install / update

From the repo root (needs sudo for systemd + nginx):

```bash
bash deploy/install.sh
```

This syncs Python deps, builds `ui/dist`, installs the unit and Nginx site, then restarts/reloads.

## Backend-only restart

```bash
sudo systemctl restart smart-automator
```

## Logs

```bash
journalctl -u smart-automator -f
```

## Env

Keep secrets in the repo-root `.env`. Production expects at least:

- `CORS_ORIGINS=http://156.67.83.177:6500`
- `HEADLESS=true`

Do not set `SESSION_COOKIE_SECURE` while serving plain HTTP.
