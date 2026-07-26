# Smart Automator Connect (C)

Small cross-platform GUI that replaces `scripts/smart-automator-connect.sh`.

Run it on the machine where **Chrome should appear**. Smart Automator stays on the gaming/server PC.

## What it does

1. Starts Chrome with remote debugging enabled
2. Picks **LAN** or **remote** mode (or auto-detects)
3. **LAN**: exposes Chrome CDP on your LAN IP (no SSH)
4. **Remote**: opens an SSH reverse tunnel with key auth (password once on first connect)
5. Shows the CDP URL and UI URL to use on the gaming PC

## Build (Linux)

```bash
sudo apt install build-essential cmake pkg-config libgtk-3-dev openssh-client

cd apps/smart-automator-connect
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/smart-automator-connect
```

Both `build/smart-automator-connect` and `build/sa-askpass` must be in the same directory.

## Build (Windows, MSYS2 MinGW64)

```bash
pacman -S --needed mingw-w64-x86_64-gcc mingw-w64-x86_64-cmake mingw-w64-x86_64-pkg-config mingw-w64-x86_64-gtk3

cd apps/smart-automator-connect
cmake -B build -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/smart-automator-connect.exe
```

## Usage

1. Click **+ Add connection** and enter name, server PC IP, SSH user, and mode
2. Click **Connect** on a saved connection
3. On the **first remote connect**, enter the SSH password once — the app installs an SSH key on the gaming PC
4. Later connects use the key automatically (no password prompt)
5. Copy the **CDP URL** into Smart Automator on the gaming PC
6. Open the **UI URL** in your browser

## Saved connections

Connections are stored in:

- Linux: `~/.config/smart-automator/connections.conf` (mode `0600`)
- Windows: `%APPDATA%\smart-automator\connections.conf`

Each entry has a name, host, user, mode, optional local IP, Chrome profile choice, and whether the SSH key is installed.

If you have an old single-profile `connect.conf`, it is migrated automatically into one saved connection named **Gaming PC** on first launch.

## Chrome profiles (this PC)

Each saved connection can use a **local** Chrome profile on the machine where Connect runs:

- **App profile** (default): dedicated directory at `~/.local/share/smart-automator-chrome`
- **System profiles**: your normal Chrome/Chromium profiles discovered from this PC (e.g. `Chrome — Person 1`). Connect copies the profile into a mirror directory under `~/.local/share/smart-automator-chrome/mirrors/` and launches that copy with remote debugging, so it does not conflict with an already-open Chrome.

These are **not** the profiles shown in the Smart Automator dashboard on the gaming PC. Connect launches Chrome here; the dashboard profile picker applies when Chrome runs on the server.

To switch profiles: **Disconnect**, edit the connection (or pick another), choose a different Chrome profile, then **Connect** again.

**Note:** System profiles are mirrored locally before connect (first time may take a few seconds). You can keep normal Chrome open; Connect uses the mirror, not your live profile session. Re-connect refreshes the mirror from disk.

## SSH keys

The app keeps one Ed25519 keypair for all connections:

- Linux: `~/.config/smart-automator/ssh/id_ed25519`
- Windows: `%APPDATA%\smart-automator\ssh\id_ed25519`

On first connect to a remote host, the password is used once to append the public key to `~/.ssh/authorized_keys` on the gaming PC. Passwords are **not** saved to disk.

If you change a connection's host or user, you will be prompted for the password again on the next connect.

## Defaults

| Setting | Default |
|---------|---------|
| SSH user | `smartprints` |
| UI port | `8400` |
| Chrome debug port | `9222` |
| Remote CDP port | `9224` |
| LAN CDP port | `9223` |

## Tunnel cleanup

Closing the app or clicking **Disconnect** stops the SSH tunnel. The SSH process is tied to the app so remote port `9224` is released when you exit.
