# Smart Automator Connect (C)

Desktop worker that runs on the machine where **Chrome should appear**. It stays online over an authenticated WebSocket; the Smart Automator server starts Chrome on this PC only when a run begins, and tunnels CDP over the same connection.

## What it does

1. Signs in once (`POST /api/workers/login`) and stores a worker token locally
2. Keeps a WebSocket to `/ws/workers?token=…` (WSS when the server URL is HTTPS)
3. Advertises local Chrome profiles to the dashboard
4. On `browser.start`, launches Chrome with remote debugging and reports `browser.ready`
5. Relays CDP through a binary mux so Playwright on the server talks to localhost while Chrome runs here

Legacy SSH reverse-tunnel / LAN CDP-proxy sources are **not** part of this build.

## Build (Linux)

```bash
sudo apt install build-essential cmake pkg-config libgtk-3-dev libssl-dev

cd apps/smart-automator-connect
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/smart-automator-connect
```

## Build (Windows, MSYS2 MinGW64)

```bash
pacman -S --needed mingw-w64-x86_64-gcc mingw-w64-x86_64-cmake mingw-w64-x86_64-pkg-config mingw-w64-x86_64-gtk3 mingw-w64-x86_64-openssl

cd apps/smart-automator-connect
cmake -B build -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/smart-automator-connect.exe
```

## Usage

1. Enter the Smart Automator **server URL** (e.g. `https://qa.example.com`), username, and password
2. Click **Connect** — the app signs in and stays online
3. Start a run from the dashboard; Connect launches Chrome when the server sends `browser.start`
4. When reconnecting fails after several attempts, click **Reconnect** (or **Log out** and sign in again)

Session file (mode `0600` on Linux):

- Linux: `~/.config/smart-automator/worker.conf`
- Windows: `%APPDATA%\smart-automator\worker.conf`

## TLS

HTTPS/WSS connections verify the server certificate against the system CA store (and check the hostname).

For lab / self-signed servers only:

```bash
SMART_AUTOMATOR_INSECURE_TLS=1 ./build/smart-automator-connect
```

Do not use that bypass in production.

## Chrome profiles

Profiles discovered on this PC are sent to the server as `profiles`. The dashboard can pick a profile for a run; Connect launches Chrome with the requested user-data / profile directory (or a fresh isolated profile when `fresh_profile` is set).

Chrome uses an ephemeral debug port (`--remote-debugging-port=0`); Connect waits for DevTools readiness before sending `browser.ready`.

## Protocol (summary)

| Plane | Transport | Role |
|-------|-----------|------|
| Control | JSON text frames | `hello`, `profiles`, `browser.start` / `ready` / `stop` / `stopped`, `error`, `ping` / `pong` |
| CDP | Binary frames | 9-byte mux header (`conn_id`, flags, length) + payload; flags `DATA=0`, `OPEN=1`, `CLOSE=2` |

The server opens a localhost CDP proxy for Playwright and sends mux `OPEN` when a client connects; Connect dials local Chrome and relays bytes.
