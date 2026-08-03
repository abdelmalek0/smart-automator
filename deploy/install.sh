#!/usr/bin/env bash
# Idempotent install / update for Smart Automator on this VPS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$ROOT/deploy"
UNIT_SRC="$DEPLOY/smart-automator.service"
NGINX_SRC="$DEPLOY/nginx.conf"
NODE_BIN="${NODE_BIN:-/home/ml/.nvm/versions/node/v22.17.0/bin}"
UV_BIN="${UV_BIN:-/home/ml/.local/bin/uv}"

export PATH="$NODE_BIN:/home/ml/.local/bin:$PATH"

run_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi
  if sudo -n true 2>/dev/null; then
    sudo "$@"
    return
  fi
  # Fallback when interactive sudo is unavailable (Docker group present).
  if command -v docker >/dev/null 2>&1; then
    local cmd
    cmd=$(printf '%q ' "$@")
    docker run --rm --privileged --pid=host alpine nsenter -t 1 -m -u -i -n sh -c "$cmd"
    return
  fi
  echo "ERROR: need root (sudo or docker) to install systemd/nginx" >&2
  exit 1
}

install_files_as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    cp "$UNIT_SRC" /etc/systemd/system/smart-automator.service
    cp "$NGINX_SRC" /etc/nginx/sites-available/smart-automator
    ln -sfn /etc/nginx/sites-available/smart-automator /etc/nginx/sites-enabled/smart-automator
    return
  fi
  if sudo -n true 2>/dev/null; then
    sudo cp "$UNIT_SRC" /etc/systemd/system/smart-automator.service
    sudo cp "$NGINX_SRC" /etc/nginx/sites-available/smart-automator
    sudo ln -sfn /etc/nginx/sites-available/smart-automator /etc/nginx/sites-enabled/smart-automator
    return
  fi
  if command -v docker >/dev/null 2>&1; then
    docker run --rm \
      -v "$UNIT_SRC:/src/smart-automator.service:ro" \
      -v "$NGINX_SRC:/src/nginx.conf:ro" \
      -v /etc/systemd/system:/etc/systemd/system \
      -v /etc/nginx/sites-available:/etc/nginx/sites-available \
      -v /etc/nginx/sites-enabled:/etc/nginx/sites-enabled \
      alpine sh -c '
        cp /src/smart-automator.service /etc/systemd/system/smart-automator.service
        cp /src/nginx.conf /etc/nginx/sites-available/smart-automator
        ln -sfn /etc/nginx/sites-available/smart-automator /etc/nginx/sites-enabled/smart-automator
      '
    return
  fi
  echo "ERROR: need root (sudo or docker) to install systemd/nginx" >&2
  exit 1
}

echo "==> Syncing Python deps"
(cd "$ROOT" && "$UV_BIN" sync)

echo "==> Building UI"
(cd "$ROOT/ui" && npm ci && npm run build)

if [[ ! -f "$ROOT/ui/dist/index.html" ]]; then
  echo "ERROR: ui/dist/index.html missing after build" >&2
  exit 1
fi

echo "==> Opening firewall (UFW)"
if command -v ufw >/dev/null 2>&1; then
  run_root ufw allow 6500/tcp comment smart-automator
else
  echo "    (ufw not installed — skip)"
fi

echo "==> Installing systemd unit + Nginx site"
install_files_as_root
run_root systemctl daemon-reload
run_root systemctl enable --now smart-automator.service
run_root systemctl restart smart-automator.service
run_root nginx -t
run_root systemctl reload nginx

echo "==> Done"
echo "    Public:  http://156.67.83.177:6500"
echo "    API:     http://127.0.0.1:6501 (loopback only)"
systemctl --no-pager --full status smart-automator.service || true
