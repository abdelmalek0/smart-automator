"""Authenticated Connect workers: token store, registry, CDP proxy over WSS."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import secrets
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from fastapi import WebSocket

from ..db.engine import get_session
from ..db.models import WorkerTokenRow
from . import paths
from .auth.stores import User

log = logging.getLogger(__name__)

WORKER_BROWSER_TIMEOUT_SECONDS = 120.0
WORKER_BROWSER_STOP_TIMEOUT_SECONDS = 5.0
_MUX_HEADER = struct.Struct("!IBI")  # conn_id u32, flags u8, length u32
FLAG_DATA = 0
FLAG_OPEN = 1
FLAG_CLOSE = 2
_LOCAL_WS_URL_RE = re.compile(r"ws://(?:127\.0\.0\.1|localhost):\d+")
_LOCAL_HTTP_URL_RE = re.compile(r"http://(?:127\.0\.0\.1|localhost):\d+")
# Coalesce consecutive DATA mux frames under this payload size before one WS send.
_OUTBOX_COALESCE_MAX = 56 * 1024
_OUTBOX_MAX_BYTES = 8 * 1024 * 1024
_OUTBOX_BATCH_ITEMS = 64
_OUTBOX_BATCH_BYTES = 256 * 1024
_WRITER_MAX_BYTES = 4 * 1024 * 1024

LOCAL_BROWSER_ENV = "SMART_AUTOMATOR_LOCAL_BROWSER"


def local_browser_mode_enabled() -> bool:
    return os.getenv(LOCAL_BROWSER_ENV, "").lower() in {"1", "true", "yes"}


ACTIVE_RUN_STATUSES = ("pending", "running", "awaiting_human")


def connect_worker_busy(user_id: str) -> bool:
    registry = worker_registry()
    worker = registry.get(user_id)
    if worker is None:
        return False
    expire = getattr(registry, "expire_stop_if_due", None)
    with worker.lease_lock:
        if expire is not None:
            expire(worker)
        return worker.browser_state not in ("idle",)


def user_has_active_run(user_id: str) -> bool:
    from .run_state import has_in_memory_active_run

    return has_in_memory_active_run(user_id)


def check_run_start_allowed(user_id: str) -> None:
    """Raise HTTPException when the user cannot start another run."""
    from fastapi import HTTPException

    if user_has_active_run(user_id):
        raise HTTPException(
            status_code=409,
            detail="Another run is already in progress",
        )

    if local_browser_mode_enabled():
        return

    worker = worker_registry().get(user_id)
    if worker is None:
        raise HTTPException(
            status_code=503,
            detail="Connect app offline",
        )

    if connect_worker_busy(user_id):
        raise HTTPException(
            status_code=409,
            detail="Connect browser is busy with another run",
        )


@dataclass
class WorkerToken:
    token: str
    user_id: str
    created_at: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerToken:
        return cls(
            token=str(data["token"]),
            user_id=str(data["user_id"]),
            created_at=float(data.get("created_at", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "user_id": self.user_id,
            "created_at": self.created_at,
        }


class WorkerTokenStore:
    def __init__(self, path: Path | None = None) -> None:
        # path is ignored; kept for backward compatibility with tests.
        self._lock = threading.Lock()

    def create_token(self, user_id: str) -> WorkerToken:
        token = WorkerToken(
            token=secrets.token_urlsafe(32),
            user_id=user_id,
            created_at=time.time(),
        )
        with self._lock:
            with get_session() as session:
                session.execute(delete(WorkerTokenRow).where(WorkerTokenRow.user_id == user_id))
                session.add(
                    WorkerTokenRow(
                        token=token.token,
                        user_id=token.user_id,
                        created_at=token.created_at,
                    )
                )
        return token

    def get_by_token(self, token: str) -> WorkerToken | None:
        if not token:
            return None
        with self._lock:
            with get_session() as session:
                row = session.get(WorkerTokenRow, token)
                if row is None:
                    return None
                return WorkerToken(
                    token=row.token,
                    user_id=row.user_id,
                    created_at=row.created_at,
                )

    def delete_for_user(self, user_id: str) -> None:
        with self._lock:
            with get_session() as session:
                session.execute(delete(WorkerTokenRow).where(WorkerTokenRow.user_id == user_id))

    def delete_token(self, token: str) -> None:
        with self._lock:
            with get_session() as session:
                session.execute(delete(WorkerTokenRow).where(WorkerTokenRow.token == token))


def pack_mux_frame(conn_id: int, flags: int, payload: bytes = b"") -> bytes:
    return _MUX_HEADER.pack(conn_id & 0xFFFFFFFF, flags & 0xFF, len(payload)) + payload


def unpack_mux_frames(buffer: bytearray) -> list[tuple[int, int, bytes]]:
    """Parse mux frames using an offset, then compact once."""
    frames: list[tuple[int, int, bytes]] = []
    offset = 0
    length = len(buffer)
    while offset + _MUX_HEADER.size <= length:
        conn_id, flags, payload_len = _MUX_HEADER.unpack_from(buffer, offset)
        total = _MUX_HEADER.size + payload_len
        if offset + total > length:
            break
        start = offset + _MUX_HEADER.size
        end = offset + total
        frames.append((conn_id, flags, bytes(buffer[start:end])))
        offset = end
    if offset:
        del buffer[:offset]
    return frames


def _parse_single_mux_frame(frame: bytes) -> tuple[int, int, bytes] | None:
    if len(frame) < _MUX_HEADER.size:
        return None
    conn_id, flags, length = _MUX_HEADER.unpack_from(frame, 0)
    if len(frame) != _MUX_HEADER.size + length:
        return None
    return conn_id, flags, frame[_MUX_HEADER.size :]


class _ProxyClientWriter:
    """Background writer so WSS receive never blocks on Playwright TCP sendall."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._queue: queue.SimpleQueue[bytes | None] = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="cdp-proxy-writer")
        self._closed = False
        self._queued_bytes = 0
        self._lock = threading.Lock()
        self._thread.start()

    def write(self, data: bytes) -> None:
        if self._closed or not data:
            return
        with self._lock:
            if self._closed:
                return
            if self._queued_bytes + len(data) > _WRITER_MAX_BYTES:
                raise OSError("CDP proxy writer backpressure")
            self._queued_bytes += len(data)
            self._queue.put(data)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._queue.put(None)
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            with self._lock:
                self._queued_bytes = max(0, self._queued_bytes - len(item))
            try:
                self._sock.sendall(item)
            except OSError:
                return


class CdpProxy:
    """Localhost TCP listener that muxes CDP sockets over the worker WSS."""

    def __init__(self, worker: WorkerConnection) -> None:
        self._worker = worker
        self._sock: socket.socket | None = None
        self._port = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._clients: dict[int, _ProxyClientWriter] = {}
        self._next_conn_id = 1

    @property
    def port(self) -> int:
        return self._port

    @property
    def cdp_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def start(self) -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(32)
        sock.settimeout(0.5)
        self._sock = sock
        self._port = sock.getsockname()[1]
        self._stop.clear()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True, name="cdp-proxy")
        self._thread.start()
        return self.cdp_url

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            clients = list(self._clients.items())
            self._clients.clear()
        for conn_id, client in clients:
            client.close()
            self._worker.enqueue_binary(pack_mux_frame(conn_id, FLAG_CLOSE))
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def handle_mux_frame(self, conn_id: int, flags: int, payload: bytes) -> None:
        with self._lock:
            client = self._clients.get(conn_id)
        if flags == FLAG_CLOSE:
            if client is not None:
                client.close()
                with self._lock:
                    self._clients.pop(conn_id, None)
            return
        if client is None:
            return
        if flags == FLAG_DATA and payload:
            try:
                client.write(self._rewrite_cdp_payload(payload))
            except OSError:
                self._close_client(conn_id)

    def _rewrite_cdp_payload(self, payload: bytes) -> bytes:
        """Rewrite Chrome debugger URLs so Playwright dials this proxy (any local port)."""
        if self._port <= 0:
            return payload
        if b"webSocketDebuggerUrl" not in payload and b"devtools" not in payload:
            return payload
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            return payload
        proxy_ws = f"ws://127.0.0.1:{self._port}"
        proxy_http = f"http://127.0.0.1:{self._port}"
        rewritten = _LOCAL_WS_URL_RE.sub(proxy_ws, text)
        rewritten = _LOCAL_HTTP_URL_RE.sub(proxy_http, rewritten)
        if rewritten == text:
            return payload
        return rewritten.encode("utf-8")

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                client, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            writer = _ProxyClientWriter(client)
            with self._lock:
                conn_id = self._next_conn_id
                self._next_conn_id += 1
                self._clients[conn_id] = writer
            self._worker.enqueue_binary(pack_mux_frame(conn_id, FLAG_OPEN))
            threading.Thread(
                target=self._client_read_loop,
                args=(conn_id, client),
                daemon=True,
                name=f"cdp-proxy-{conn_id}",
            ).start()

    def _client_read_loop(self, conn_id: int, client: socket.socket) -> None:
        chunk_size = 48 * 1024
        try:
            while not self._stop.is_set():
                try:
                    data = client.recv(chunk_size)
                except OSError:
                    break
                if not data:
                    break
                self._worker.enqueue_binary(pack_mux_frame(conn_id, FLAG_DATA, data))
        finally:
            self._close_client(conn_id)

    def _close_client(self, conn_id: int) -> None:
        with self._lock:
            client = self._clients.pop(conn_id, None)
        if client is not None:
            client.close()
            self._worker.enqueue_binary(pack_mux_frame(conn_id, FLAG_CLOSE))

    def close_client(self, conn_id: int) -> None:
        """Public wrapper used when outbox backpressure must reset a CDP stream."""
        self._close_client(conn_id)


@dataclass
class WorkerConnection:
    user_id: str
    websocket: WebSocket
    loop: asyncio.AbstractEventLoop
    online: bool = True
    last_seen: float = field(default_factory=time.time)
    profiles: list[dict[str, Any]] = field(default_factory=list)
    browser_state: str = "idle"  # idle | starting | ready | stopping
    active_run_id: str | None = None
    stop_deadline: float | None = None
    cdp_proxy: CdpProxy | None = None
    cdp_url: str | None = None
    ready_event: threading.Event = field(default_factory=threading.Event)
    stopped_event: threading.Event = field(default_factory=threading.Event)
    error_message: str = ""
    lease_lock: threading.Lock = field(default_factory=threading.Lock)
    # Thread-safe outbox: proxy threads enqueue here; drain_outbox sends on the event loop.
    _sync_outbox: queue.SimpleQueue = field(default_factory=queue.SimpleQueue)
    _outbox_bytes: int = 0
    _outbox_lock: threading.Lock = field(default_factory=threading.Lock)
    _wake_pending: bool = False
    _outbox_wake: asyncio.Event | None = field(default=None, init=False, repr=False)
    _binary_buffer: bytearray = field(default_factory=bytearray)

    def touch(self) -> None:
        self.last_seen = time.time()

    def _signal_outbox(self) -> None:
        with self._outbox_lock:
            if self._wake_pending:
                return
            self._wake_pending = True

        def _wake() -> None:
            with self._outbox_lock:
                self._wake_pending = False
            if self._outbox_wake is not None:
                self._outbox_wake.set()

        try:
            self.loop.call_soon_threadsafe(_wake)
        except RuntimeError:
            with self._outbox_lock:
                self._wake_pending = False
            log.warning("worker outbox wake failed user=%s", self.user_id[:8])

    def enqueue_json(self, payload: dict[str, Any]) -> None:
        # Control messages always accepted — they are small and latency-critical.
        try:
            with self._outbox_lock:
                self._sync_outbox.put(("json", payload))
            self._signal_outbox()
        except Exception:
            log.warning("worker outbox enqueue failed user=%s", self.user_id[:8])

    def enqueue_binary(self, payload: bytes) -> None:
        try:
            parsed = _parse_single_mux_frame(payload) if payload else None
            flags = parsed[1] if parsed is not None else FLAG_DATA
            # OPEN/CLOSE are control-plane mux — always accept like JSON.
            is_control_mux = flags in (FLAG_OPEN, FLAG_CLOSE)
            overflow_conn: int | None = None
            with self._outbox_lock:
                if (
                    not is_control_mux
                    and self._outbox_bytes + len(payload) > _OUTBOX_MAX_BYTES
                ):
                    overflow_conn = parsed[0] if parsed is not None else None
                else:
                    self._sync_outbox.put(("bin", payload))
                    self._outbox_bytes += len(payload)
            if overflow_conn is not None:
                log.warning(
                    "worker outbox backpressure user=%s conn=%s — closing client",
                    self.user_id[:8],
                    overflow_conn,
                )
                proxy = self.cdp_proxy
                if proxy is not None:
                    proxy.close_client(overflow_conn)
                return
            self._signal_outbox()
        except Exception:
            log.warning("worker binary enqueue failed user=%s", self.user_id[:8])

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self.websocket.send_json(payload)

    async def send_bytes(self, payload: bytes) -> None:
        await self.websocket.send_bytes(payload)

    @staticmethod
    def _coalesce_outbox_items(
        items: list[tuple[str, Any]],
    ) -> list[tuple[str, Any]]:
        """Merge consecutive FLAG_DATA mux frames for the same conn_id.

        Preserves enqueue order so browser.start cannot leapfrog earlier CLOSE frames.
        """
        if not items:
            return items
        out: list[tuple[str, Any]] = []
        pending_conn: int | None = None
        pending_parts: list[bytes] = []
        pending_size = 0

        def flush_pending() -> None:
            nonlocal pending_conn, pending_parts, pending_size
            if pending_conn is None or not pending_parts:
                pending_conn = None
                pending_parts = []
                pending_size = 0
                return
            if len(pending_parts) == 1:
                out.append(("bin", pack_mux_frame(pending_conn, FLAG_DATA, pending_parts[0])))
            else:
                out.append(
                    ("bin", pack_mux_frame(pending_conn, FLAG_DATA, b"".join(pending_parts)))
                )
            pending_conn = None
            pending_parts = []
            pending_size = 0

        for kind, payload in items:
            if kind != "bin" or not isinstance(payload, (bytes, bytearray)):
                flush_pending()
                out.append((kind, payload))
                continue
            parsed = _parse_single_mux_frame(bytes(payload))
            if parsed is None or parsed[1] != FLAG_DATA or not parsed[2]:
                flush_pending()
                out.append((kind, payload))
                continue
            conn_id, _flags, data = parsed
            if pending_conn is not None and (
                conn_id != pending_conn or pending_size + len(data) > _OUTBOX_COALESCE_MAX
            ):
                flush_pending()
            pending_conn = conn_id
            pending_parts.append(data)
            pending_size += len(data)
        flush_pending()
        return out

    async def _flush_sync_outbox(self) -> int:
        batch: list[tuple[str, Any]] = []
        batch_bytes = 0
        while len(batch) < _OUTBOX_BATCH_ITEMS and batch_bytes < _OUTBOX_BATCH_BYTES:
            try:
                item = self._sync_outbox.get_nowait()
            except queue.Empty:
                break
            kind, payload = item
            with self._outbox_lock:
                if kind == "bin" and isinstance(payload, (bytes, bytearray)):
                    self._outbox_bytes = max(0, self._outbox_bytes - len(payload))
            batch.append(item)
            if isinstance(payload, (bytes, bytearray)):
                batch_bytes += len(payload)
            else:
                batch_bytes += 64
        if not batch:
            return 0
        coalesced = self._coalesce_outbox_items(batch)
        for kind, payload in coalesced:
            if kind == "json":
                await self.send_json(payload)
            else:
                await self.send_bytes(payload)
        return len(coalesced)

    async def drain_outbox(self) -> None:
        self._outbox_wake = asyncio.Event()
        wake = self._outbox_wake
        try:
            while self.online:
                flushed = await self._flush_sync_outbox()
                if flushed:
                    # Yield so receive/control can run between large batches.
                    await asyncio.sleep(0)
                    continue
                wake.clear()
                # Re-check after clear — avoid missing a wake that raced with flush.
                if await self._flush_sync_outbox():
                    await asyncio.sleep(0)
                    continue
                try:
                    await asyncio.wait_for(wake.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    await self.send_json({"type": "ping"})
                    continue
                wake.clear()
                await self._flush_sync_outbox()
        except Exception:
            self.online = False
            try:
                await self.websocket.close(code=1011)
            except Exception:
                pass
            raise


class WorkerRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._workers: dict[str, WorkerConnection] = {}

    def register(self, worker: WorkerConnection) -> None:
        with self._lock:
            previous = self._workers.get(worker.user_id)
            self._workers[worker.user_id] = worker
        if previous is not None and previous is not worker:
            previous.online = False
            self._teardown_proxy(previous, blocking=False)
            try:
                asyncio.run_coroutine_threadsafe(previous.websocket.close(code=1000), previous.loop)
            except RuntimeError:
                pass

    def unregister(self, worker: WorkerConnection) -> None:
        with self._lock:
            current = self._workers.get(worker.user_id)
            if current is worker:
                del self._workers[worker.user_id]
        worker.online = False
        with worker.lease_lock:
            self._release_lease_locked(worker, blocking=False)
        worker.ready_event.set()

    def get(self, user_id: str) -> WorkerConnection | None:
        with self._lock:
            worker = self._workers.get(user_id)
            if worker is None or not worker.online:
                return None
            return worker

    def status_for_user(self, user_id: str) -> dict[str, Any]:
        worker = self.get(user_id)
        if worker is None:
            return {
                "online": False,
                "last_seen": None,
                "profile_count": 0,
                "browser_state": "offline",
                "active_run_id": None,
            }
        with worker.lease_lock:
            self.expire_stop_if_due(worker)
            return {
                "online": True,
                "last_seen": worker.last_seen,
                "profile_count": len(worker.profiles),
                "browser_state": worker.browser_state,
                "active_run_id": worker.active_run_id,
            }

    def profiles_for_user(self, user_id: str) -> list[dict[str, Any]]:
        worker = self.get(user_id)
        if worker is None:
            return []
        return list(worker.profiles)

    def resolve_profile_for_start(
        self,
        user_id: str,
        *,
        chrome_user_data: str,
        chrome_profile_directory: str,
    ) -> tuple[str, str]:
        """Return Connect launch profile dirs from Settings; app-default when both empty."""
        worker = self.get(user_id)
        if worker is None:
            return "", ""
        user_data = (chrome_user_data or "").strip()
        profile_dir = (chrome_profile_directory or "").strip()
        if not user_data and not profile_dir:
            return "", ""
        for profile in worker.profiles:
            pud = str(profile.get("user_data_dir") or "").strip()
            pdir = str(profile.get("profile_directory") or "").strip()
            if user_data and pud == user_data and (not profile_dir or pdir == profile_dir):
                return pud, pdir
            if user_data and pud == user_data and profile_dir == pdir:
                return pud, pdir
        log.warning(
            "Settings chrome profile %s/%s not in Connect advertised profiles; passing through",
            user_data or "(empty)",
            profile_dir or "(empty)",
        )
        return user_data, profile_dir

    def request_browser_start(
        self,
        user_id: str,
        *,
        run_id: str,
        fresh_profile: bool,
        chrome_user_data: str = "",
        chrome_profile_directory: str = "",
        timeout: float = WORKER_BROWSER_TIMEOUT_SECONDS,
    ) -> str:
        worker = self.get(user_id)
        if worker is None:
            raise RuntimeError("Connect app offline")

        deadline = time.monotonic() + timeout
        while True:
            with worker.lease_lock:
                self.expire_stop_if_due(worker)
                if worker.browser_state == "stopping":
                    busy = True
                else:
                    busy = (
                        worker.browser_state not in ("idle",)
                        and worker.active_run_id not in (None, run_id)
                    )
                if not busy:
                    self._teardown_proxy(worker, blocking=True)
                    worker.error_message = ""
                    worker.ready_event.clear()
                    worker.stopped_event.clear()
                    worker.stop_deadline = None
                    worker.browser_state = "starting"
                    worker.active_run_id = run_id
                    worker.cdp_url = None

                    proxy = CdpProxy(worker)
                    try:
                        cdp_url = proxy.start()
                    except Exception:
                        worker.browser_state = "idle"
                        worker.active_run_id = None
                        raise
                    worker.cdp_proxy = proxy
                    worker.cdp_url = cdp_url

                    worker.enqueue_json(
                        {
                            "type": "browser.start",
                            "run_id": run_id,
                            "fresh_profile": bool(fresh_profile),
                            "chrome_user_data": chrome_user_data or "",
                            "chrome_profile_directory": chrome_profile_directory or "",
                        }
                    )
                    break

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Connect browser is busy with another run")
            worker.stopped_event.wait(timeout=min(1.0, remaining))
            worker.stopped_event.clear()

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for Connect browser to become ready")
                if worker.ready_event.wait(timeout=min(1.0, remaining)):
                    worker.ready_event.clear()
                    if worker.error_message:
                        raise RuntimeError(worker.error_message)
                    if worker.online and worker.browser_state == "ready" and worker.cdp_url:
                        break
                    if not worker.online:
                        raise RuntimeError("Connect app offline")
                    # Spurious wake (e.g. browser.stopped during relaunch) — keep waiting.

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for CDP /json/version")
            self._wait_json_version(worker.cdp_url, timeout=remaining)
            return worker.cdp_url
        except Exception:
            self.request_browser_stop(user_id, run_id=run_id, wait=False)
            raise

    def detach_cdp_proxy(
        self,
        user_id: str,
        *,
        run_id: str | None = None,
    ) -> None:
        """Stop muxing CDP without asking Connect to kill Chrome.

        Call before Playwright cleanup so local proxy sockets die first and
        cleanup does not flood the worker control WSS.
        """
        worker = self.get(user_id)
        if worker is None:
            return
        with worker.lease_lock:
            if run_id is not None and worker.active_run_id not in (None, run_id):
                return
            self._teardown_proxy(worker, blocking=True)
            worker.cdp_url = None

    def request_browser_stop(
        self,
        user_id: str,
        *,
        run_id: str | None = None,
        wait: bool = True,
        timeout: float = WORKER_BROWSER_STOP_TIMEOUT_SECONDS,
    ) -> None:
        worker = self.get(user_id)
        if worker is None:
            return
        wait_seconds = 0.0
        with worker.lease_lock:
            if run_id is not None and worker.active_run_id not in (None, run_id):
                return
            if worker.browser_state == "idle" and worker.cdp_proxy is None:
                return

            if worker.browser_state != "stopping":
                worker.browser_state = "stopping"
                worker.stop_deadline = time.monotonic() + max(0.0, timeout)
                worker.stopped_event.clear()
                worker.enqueue_json(
                    {"type": "browser.stop", "run_id": run_id or worker.active_run_id or ""}
                )
            if wait:
                remaining = (
                    (worker.stop_deadline - time.monotonic())
                    if worker.stop_deadline is not None
                    else timeout
                )
                wait_seconds = max(0.0, remaining)

        if wait:
            worker.stopped_event.wait(timeout=wait_seconds)
            with worker.lease_lock:
                if (
                    worker.browser_state == "stopping"
                    and (run_id is None or worker.active_run_id in (None, run_id))
                ):
                    self._release_lease_locked(worker, blocking=True)

    def expire_stop_if_due(self, worker: WorkerConnection) -> None:
        """Force idle if a stop never got browser.stopped. Caller holds lease_lock."""
        if worker.browser_state != "stopping":
            return
        deadline = worker.stop_deadline
        if deadline is not None and time.monotonic() < deadline:
            return
        self._release_lease_locked(worker, blocking=False)

    def _release_lease_locked(self, worker: WorkerConnection, *, blocking: bool) -> None:
        """Caller holds lease_lock."""
        self._teardown_proxy(worker, blocking=blocking)
        worker.browser_state = "idle"
        worker.active_run_id = None
        worker.cdp_url = None
        worker.stop_deadline = None
        worker.stopped_event.set()

    def handle_control_message(self, worker: WorkerConnection, message: dict[str, Any]) -> None:
        worker.touch()
        msg_type = str(message.get("type") or "")
        if msg_type == "hello":
            return
        if msg_type == "profiles":
            profiles = message.get("profiles")
            if isinstance(profiles, list):
                worker.profiles = [p for p in profiles if isinstance(p, dict)]
            return
        if msg_type == "browser.starting":
            with worker.lease_lock:
                if worker.browser_state != "stopping":
                    worker.browser_state = "starting"
            return
        if msg_type == "browser.ready":
            with worker.lease_lock:
                if worker.browser_state == "stopping":
                    return
                worker.browser_state = "ready"
                worker.error_message = ""
                worker.ready_event.set()
            return
        if msg_type == "browser.stopped":
            # During an in-flight start, Connect may tear down a previous Chrome
            # before launching a new one. Do not wake the ready waiter as failure.
            with worker.lease_lock:
                if worker.browser_state == "starting":
                    worker.stopped_event.set()
                    return
                self._release_lease_locked(worker, blocking=False)
                worker.ready_event.set()
            return
        if msg_type == "error":
            with worker.lease_lock:
                worker.error_message = str(message.get("message") or "Connect worker error")
                worker.ready_event.set()
                worker.stopped_event.set()
            return
        if msg_type in ("ping", "pong"):
            if msg_type == "ping":
                worker.enqueue_json({"type": "pong"})
            return

    def handle_binary(self, worker: WorkerConnection, data: bytes) -> None:
        worker.touch()
        worker._binary_buffer.extend(data)
        frames = unpack_mux_frames(worker._binary_buffer)
        proxy = worker.cdp_proxy
        if proxy is None:
            return
        for conn_id, flags, payload in frames:
            proxy.handle_mux_frame(conn_id, flags, payload)

    @staticmethod
    def _teardown_proxy(worker: WorkerConnection, *, blocking: bool = True) -> None:
        proxy = worker.cdp_proxy
        worker.cdp_proxy = None
        if proxy is None:
            return
        if blocking:
            proxy.stop()
            return
        threading.Thread(target=proxy.stop, daemon=True, name="cdp-proxy-stop").start()

    @staticmethod
    def _wait_json_version(cdp_url: str, *, timeout: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        url = cdp_url.rstrip("/") + "/json/version"
        last_error = "CDP proxy not ready"
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                with urllib.request.urlopen(url, timeout=min(2.0, max(0.1, remaining))) as response:
                    if 200 <= response.status < 300:
                        log.info(
                            "Connect CDP ready http_json_version ok url=%s",
                            url,
                        )
                        return
                    last_error = f"CDP /json/version HTTP {response.status}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = str(exc)
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
        raise TimeoutError(f"Timed out waiting for CDP /json/version: {last_error}")


_token_store: WorkerTokenStore | None = None
_registry: WorkerRegistry | None = None


def worker_token_store() -> WorkerTokenStore:
    global _token_store
    if _token_store is None:
        _token_store = WorkerTokenStore()
    return _token_store


def worker_registry() -> WorkerRegistry:
    global _registry
    if _registry is None:
        _registry = WorkerRegistry()
    return _registry


def resolve_user_from_worker_token(token: str | None) -> User | None:
    if not token:
        return None
    record = worker_token_store().get_by_token(token)
    if record is None:
        return None
    from .auth.dependencies import user_store

    return user_store().get_by_id(record.user_id)
