#!/usr/bin/env bash
# Connect local Chrome to Smart Automator on a remote/server PC.
#
# Run on the machine where the BROWSER should appear (your PC).
# API + shared data stay on the gaming/server PC.
#
# Usage:
#   ./scripts/smart-automator-connect.sh <gaming-pc-ip> [options]
#
# Examples:
#   ./scripts/smart-automator-connect.sh 192.168.192.120
#   ./scripts/smart-automator-connect.sh 192.168.1.50 --mode lan
#   ./scripts/smart-automator-connect.sh 192.168.192.120 -u smartprints

set -euo pipefail

SSH_USER="smartprints"
GAMING_HOST=""
LOCAL_HOST=""
MODE="auto" # auto | lan | remote
UI_PORT=8400
CHROME_PORT=9222
CDP_REMOTE_PORT=9224
CDP_LAN_PORT=9223
CHROME_PROFILE="${CHROME_PROFILE:-${HOME}/.local/share/smart-automator-chrome}"

SOCAT_PID=""
SSH_CONTROL=""

usage() {
  cat <<'EOF'
Usage: smart-automator-connect.sh <gaming-pc-ip> [options]

  Run on the machine where the BROWSER should appear.

Options:
  -u, --user USER       SSH user on gaming PC (default: smartprints)
  -l, --local IP        Your PC IP (optional; auto-detected in LAN mode)
  -m, --mode MODE       auto | lan | remote
  --ui-port PORT        API port (default: 8400)
  --chrome-port PORT    Chrome debug port here (default: 9222)
  --cdp-remote-port P   SSH reverse CDP port on gaming PC (default: 9224)
  --cdp-lan-port P      Direct CDP port on your PC in LAN mode (default: 9223)
  -h, --help

Modes:
  lan     Same network — socat only, no SSH
  remote  ZeroTier / away — SSH reverse tunnel for CDP
  auto    192.168.192.* → remote; else LAN if API reachable, else remote

CDP URL (set in Smart Automator on the gaming PC):
  remote  http://127.0.0.1:9224
  lan     http://<your-pc-ip>:9223
EOF
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -u|--user)           SSH_USER="$2"; shift 2 ;;
    -l|--local)          LOCAL_HOST="$2"; shift 2 ;;
    -m|--mode)           MODE="$2"; shift 2 ;;
    --ui-port)           UI_PORT="$2"; shift 2 ;;
    --chrome-port)       CHROME_PORT="$2"; shift 2 ;;
    --cdp-remote-port)   CDP_REMOTE_PORT="$2"; shift 2 ;;
    --cdp-lan-port)      CDP_LAN_PORT="$2"; shift 2 ;;
    -h|--help)           usage 0 ;;
    -*)                  echo "Unknown option: $1" >&2; usage 1 ;;
    *)                   [[ -z "$GAMING_HOST" ]] && GAMING_HOST="$1" || { echo "Extra arg: $1" >&2; exit 1; }; shift ;;
  esac
done

[[ -n "$GAMING_HOST" ]] || { echo "Gaming PC IP required." >&2; usage 1; }

GAMING_PC="${SSH_USER}@${GAMING_HOST}"

find_chrome() {
  for bin in google-chrome google-chrome-stable chromium chromium-browser; do
    command -v "$bin" >/dev/null 2>&1 && echo "$bin" && return 0
  done
  return 1
}

chrome_ready() {
  curl -sf "http://127.0.0.1:${CHROME_PORT}/json/version" >/dev/null 2>&1
}

detect_local_ip() {
  if [[ -n "$LOCAL_HOST" ]]; then
    echo "$LOCAL_HOST"
    return
  fi
  ip -4 route get "$GAMING_HOST" 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") print $(i + 1)}' | head -1
}

is_zerotier_ip() {
  [[ "$GAMING_HOST" =~ ^192\.168\.192\. ]]
}

api_reachable() {
  curl -sf --connect-timeout 2 "http://${GAMING_HOST}:${UI_PORT}/api/runs" >/dev/null 2>&1
}

resolve_mode() {
  case "$MODE" in
    lan|remote) echo "$MODE"; return ;;
    auto)
      if is_zerotier_ip "$GAMING_HOST"; then
        echo "remote"
      elif api_reachable; then
        echo "lan"
      else
        echo "remote"
      fi
      ;;
    *) echo "Invalid mode: $MODE" >&2; exit 1 ;;
  esac
}

port_in_use() {
  local port="$1"
  ss -tln 2>/dev/null | grep -q ":${port} "
}

close_ssh_control() {
  if [[ -n "$SSH_CONTROL" ]]; then
    ssh -S "$SSH_CONTROL" -O exit "$GAMING_PC" 2>/dev/null || true
    rm -f "$SSH_CONTROL"
    SSH_CONTROL=""
  fi
}

cleanup() {
  echo ""
  echo "Stopping..."
  [[ -n "$SOCAT_PID" ]] && kill "$SOCAT_PID" 2>/dev/null || true
  close_ssh_control
}
trap cleanup EXIT INT TERM

start_chrome() {
  local chrome_bin
  chrome_bin="$(find_chrome)" || { echo "Chrome/Chromium not found." >&2; exit 1; }
  mkdir -p "$CHROME_PROFILE"

  if chrome_ready; then
    echo "Chrome already listening on 127.0.0.1:${CHROME_PORT}"
    return
  fi

  echo "Starting Chrome..."
  "$chrome_bin" \
    --remote-debugging-port="${CHROME_PORT}" \
    --user-data-dir="${CHROME_PROFILE}" \
    --no-first-run \
    --no-default-browser-check \
    >/dev/null 2>&1 &

  for _ in $(seq 1 40); do
    chrome_ready && break
    sleep 0.25
  done
  chrome_ready || { echo "Chrome failed to start on port ${CHROME_PORT}." >&2; exit 1; }
  echo "Chrome ready on 127.0.0.1:${CHROME_PORT}"
}

verify_lan_cdp() {
  local local_ip="$1"
  curl -sf --connect-timeout 2 "http://${local_ip}:${CDP_LAN_PORT}/json/version" >/dev/null 2>&1
}

verify_remote_cdp() {
  local port="$1"
  ssh -S "$SSH_CONTROL" -o ConnectTimeout=5 "$GAMING_PC" \
    "curl -sf --connect-timeout 2 http://127.0.0.1:${port}/json/version" >/dev/null 2>&1
}

start_remote_tunnel() {
  local port="$1"
  close_ssh_control
  SSH_CONTROL="$(mktemp -u /tmp/sa-ssh-XXXXXX)"
  rm -f "$SSH_CONTROL"

  echo "Connecting SSH to ${GAMING_PC} ..."
  echo "Enter password when prompted (connection stays in this terminal)."
  echo ""

  # -f backgrounds SSH only after password auth — avoids stealing stdin with & + poll loop
  if ! ssh -f -N -M -S "$SSH_CONTROL" \
    -o ControlPersist=10m \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -R "${port}:127.0.0.1:${CHROME_PORT}" \
    "$GAMING_PC"; then
    echo "SSH connection failed." >&2
    close_ssh_control
    return 1
  fi
  return 0
}

wait_for_remote_tunnel() {
  local port="$1"
  local attempts="${2:-30}"

  echo "Verifying CDP tunnel on gaming PC port ${port} ..."

  for ((i = 0; i < attempts; i++)); do
    if ! ssh -S "$SSH_CONTROL" -O check "$GAMING_PC" 2>/dev/null; then
      echo "SSH master connection closed." >&2
      return 1
    fi
    if verify_remote_cdp "$port"; then
      return 0
    fi
    sleep 1
  done

  echo "Timed out waiting for CDP tunnel on gaming PC port ${port}." >&2
  return 1
}

hold_ssh_tunnel() {
  while ssh -S "$SSH_CONTROL" -O check "$GAMING_PC" 2>/dev/null; do
    sleep 2
  done
  echo "SSH tunnel closed." >&2
}

print_lan_ready() {
  local local_ip="$1"
  cat <<EOF

=== LAN mode (no SSH) ===

Open UI:
  http://${GAMING_HOST}:${UI_PORT}

CDP URL in Smart Automator:
  http://${LOCAL_IP}:${CDP_LAN_PORT}

Verified from this machine. From gaming PC:
  curl http://${LOCAL_IP}:${CDP_LAN_PORT}/json/version

Leave this terminal open. Ctrl+C to stop.
EOF
}

print_remote_ready() {
  local port="$1"
  cat <<EOF

=== Remote mode (SSH CDP tunnel ready) ===

CDP URL in Smart Automator:
  http://127.0.0.1:${port}

Open UI:
  http://${GAMING_HOST}:${UI_PORT}

Tunnel verified on gaming PC:
  curl http://127.0.0.1:${port}/json/version

Leave this terminal open. Ctrl+C to stop.
EOF
}

# --- main ---

start_chrome

RESOLVED_MODE="$(resolve_mode)"
echo "Mode: ${RESOLVED_MODE}"
echo ""

if [[ "$RESOLVED_MODE" == "lan" ]]; then
  command -v socat >/dev/null 2>&1 || { echo "Install socat: sudo apt install socat" >&2; exit 1; }

  LOCAL_IP="$(detect_local_ip)"
  [[ -n "$LOCAL_IP" ]] || { echo "Could not detect local IP. Use -l <your-ip>." >&2; exit 1; }

  if port_in_use "$CDP_LAN_PORT"; then
    echo "Port ${CDP_LAN_PORT} already in use." >&2
    exit 1
  fi

  echo "Starting direct CDP proxy (no SSH) on 0.0.0.0:${CDP_LAN_PORT} ..."
  socat TCP-LISTEN:"${CDP_LAN_PORT}",bind=0.0.0.0,reuseaddr,fork TCP:127.0.0.1:"${CHROME_PORT}" &
  SOCAT_PID=$!
  sleep 0.5

  if ! verify_lan_cdp "$LOCAL_IP"; then
    echo "CDP proxy failed. Try: curl http://${LOCAL_IP}:${CDP_LAN_PORT}/json/version" >&2
    exit 1
  fi

  print_lan_ready "$LOCAL_IP"
  wait "$SOCAT_PID"
  exit 0
fi

# Remote mode: try CDP_REMOTE_PORT and fall back to next ports if bind fails.
REMOTE_PORT=""
for port in "$CDP_REMOTE_PORT" $((CDP_REMOTE_PORT + 1)) $((CDP_REMOTE_PORT + 2)); do
  if start_remote_tunnel "$port" && wait_for_remote_tunnel "$port"; then
    REMOTE_PORT="$port"
    break
  fi
  close_ssh_control
  echo "Retrying with another port..." >&2
done

if [[ -z "$REMOTE_PORT" ]]; then
  cat <<'EOF' >&2
Failed to establish SSH CDP tunnel.

Check:
  - SSH works: ssh smartprints@<gaming-pc>
  - Gaming PC sshd allows TCP forwarding (AllowTcpForwarding yes)
  - Port 9224-9226 is free on the gaming PC: ss -tlnp | grep 922
EOF
  exit 1
fi

print_remote_ready "$REMOTE_PORT"
hold_ssh_tunnel
