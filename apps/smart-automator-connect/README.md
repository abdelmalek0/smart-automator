# Smart Automator Connect

Desktop worker for the PC where Chrome should run. It stays online over an authenticated WebSocket; the Smart Automator server starts Chrome only when a run begins and tunnels CDP over the same connection.

## What it does

1. Signs in once (`POST /api/workers/login`) and stores a worker token locally
2. Keeps a WebSocket to `/ws/workers?token=…` (WSS when the server URL is HTTPS)
3. Advertises local Chrome profiles to the dashboard
4. On `browser.start`, launches Chrome with remote debugging and reports `browser.ready`
5. Relays CDP through a binary mux so Playwright on the server talks to localhost while Chrome runs here

Legacy SSH reverse-tunnel / LAN CDP-proxy sources are not part of this build.

## Build

### Linux

```bash
sudo apt install build-essential cmake pkg-config libgtk-3-dev libssl-dev

cd apps/smart-automator-connect
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/smart-automator-connect
```

### Windows (MSYS2 clang64)

Use the **clang64** shell (not mingw64 / ucrt64) so toolchain, pkg-config, and GTK share one prefix.

```bash
pacman -S --needed \
  mingw-w64-clang-x86_64-clang \
  mingw-w64-clang-x86_64-cmake \
  mingw-w64-clang-x86_64-ninja \
  mingw-w64-clang-x86_64-pkg-config \
  mingw-w64-clang-x86_64-gtk3 \
  mingw-w64-clang-x86_64-openssl

cd apps/smart-automator-connect
rm -rf build
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang
cmake --build build -j
./build/smart-automator-connect.exe
```

The Windows binary is a GUI app (no console window). After changing linker subsystem flags, wipe `build/` and reconfigure — an incremental rebuild may keep an old console-linked `.exe`.

Optional check:

```bash
llvm-readobj --file-headers build/smart-automator-connect.exe | grep Subsystem
```

## Configuration

Optional `connect.conf` next to the executable (sample: `connect.conf.example` in the build dir):

```
server_url=https://your-server.example.com
```

If missing or empty, Connect defaults to `http://156.67.83.177:6500/`.

Session file (mode `0600` on Linux):

| OS | Path |
|----|------|
| Linux | `~/.config/smart-automator/worker.conf` |
| Windows | `%APPDATA%\smart-automator\worker.conf` |

## Usage

1. Optionally place `connect.conf` beside the binary
2. Sign in with username and password
3. When the WebSocket is up, the window hides to the tray (worker keeps running)
4. Start a run from the dashboard; Connect launches Chrome on `browser.start`
5. If reconnect fails after several attempts, use **Reconnect**, or **Log out** and sign in again

### Window and tray

| Action | Connected | Not connected |
|--------|-----------|---------------|
| Close (X) | Hide to tray | Quit |
| Minimize | Hide to tray | Normal taskbar minimize |

- Tray icon (and **Log out**) appear only while a worker token is saved — not on the login form
- With a saved token, Connect opens the status page and reconnects automatically (not the login form)
- Restore the window from the tray (click / **Show window**); quit from the tray menu while connected

## Chrome profiles

Discovered profiles are sent to the server as `profiles`. The dashboard can pick one for a run; Connect launches Chrome with that user-data / profile directory, or a fresh isolated profile when `fresh_profile` is set.

Chrome uses an ephemeral debug port (`--remote-debugging-port=0`). Connect waits for DevTools readiness before `browser.ready`.

## TLS

HTTPS/WSS verifies the server certificate against the system CA store (including hostname).

Lab / self-signed only — do not use in production:

```bash
SMART_AUTOMATOR_INSECURE_TLS=1 ./build/smart-automator-connect
```

## Protocol (summary)

| Plane | Transport | Role |
|-------|-----------|------|
| Control | JSON text frames | `hello`, `profiles`, `browser.start` / `ready` / `stop` / `stopped`, `error`, `ping` / `pong` |
| CDP | Binary frames | 9-byte mux header (`conn_id`, flags, length) + payload; flags `DATA=0`, `OPEN=1`, `CLOSE=2` |

The server opens a localhost CDP proxy for Playwright and sends mux `OPEN` when a client connects; Connect dials local Chrome and relays bytes.
