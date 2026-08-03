"""Unit tests for Connect worker mux parsing and readiness helpers."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from smart_automator.server import workers
from smart_automator.server.workers import (
    FLAG_CLOSE,
    FLAG_DATA,
    FLAG_OPEN,
    WorkerConnection,
    WorkerRegistry,
    pack_mux_frame,
    unpack_mux_frames,
)


def test_unpack_mux_frames_compacts_once() -> None:
    buf = bytearray()
    buf.extend(pack_mux_frame(7, FLAG_OPEN))
    buf.extend(pack_mux_frame(7, FLAG_DATA, b"abc"))
    buf.extend(pack_mux_frame(7, FLAG_CLOSE))
    # trailing incomplete header should remain
    buf.extend(b"\x00\x00")

    frames = unpack_mux_frames(buf)
    assert frames == [(7, FLAG_OPEN, b""), (7, FLAG_DATA, b"abc"), (7, FLAG_CLOSE, b"")]
    assert bytes(buf) == b"\x00\x00"


def test_outbox_coalesce_preserves_order_across_control() -> None:
    """CLOSE before browser.start must not be leapfrogged by JSON promotion."""
    items = [
        ("bin", pack_mux_frame(1, FLAG_CLOSE)),
        ("json", {"type": "browser.start"}),
        ("bin", pack_mux_frame(2, FLAG_DATA, b"aa")),
        ("bin", pack_mux_frame(2, FLAG_DATA, b"bb")),
    ]
    out = WorkerConnection._coalesce_outbox_items(items)
    assert out[0][0] == "bin"
    assert workers._parse_single_mux_frame(out[0][1]) == (1, FLAG_CLOSE, b"")
    assert out[1] == ("json", {"type": "browser.start"})
    assert out[2][0] == "bin"
    parsed = workers._parse_single_mux_frame(out[2][1])
    assert parsed is not None
    assert parsed[0] == 2 and parsed[1] == FLAG_DATA and parsed[2] == b"aabb"


def test_outbox_data_overflow_closes_client() -> None:
    loop = MagicMock()
    worker = WorkerConnection(user_id="user-1", websocket=MagicMock(), loop=loop)
    proxy = MagicMock()
    worker.cdp_proxy = proxy
    worker._outbox_bytes = workers._OUTBOX_MAX_BYTES
    worker.enqueue_binary(pack_mux_frame(9, FLAG_DATA, b"x" * 64))
    proxy.close_client.assert_called_once_with(9)


def test_outbox_accepts_close_under_backpressure() -> None:
    loop = MagicMock()
    worker = WorkerConnection(user_id="user-1", websocket=MagicMock(), loop=loop)
    worker._outbox_bytes = workers._OUTBOX_MAX_BYTES
    frame = pack_mux_frame(3, FLAG_CLOSE)
    worker.enqueue_binary(frame)
    item = worker._sync_outbox.get_nowait()
    assert item == ("bin", frame)


def test_request_browser_start_uses_single_deadline_and_keeps_ready_gate() -> None:
    registry = WorkerRegistry()
    loop = MagicMock()
    worker = WorkerConnection(user_id="user-1", websocket=MagicMock(), loop=loop)
    registry.register(worker)

    def mark_ready_then_json_ok(cdp_url: str, *, timeout: float) -> None:
        # Readiness must already have been observed before the functional probe.
        assert worker.browser_state == "ready"
        assert timeout > 0
        assert timeout <= workers.WORKER_BROWSER_TIMEOUT_SECONDS

    with (
        patch.object(WorkerRegistry, "_teardown_proxy"),
        patch.object(workers.CdpProxy, "start", return_value="http://127.0.0.1:9999"),
        patch.object(WorkerRegistry, "_wait_json_version", side_effect=mark_ready_then_json_ok),
    ):
        def arrive():
            time.sleep(0.05)
            registry.handle_control_message(worker, {"type": "browser.ready"})

        import threading

        threading.Thread(target=arrive, daemon=True).start()
        url = registry.request_browser_start(
            "user-1",
            run_id="run-1",
            fresh_profile=True,
            timeout=2.0,
        )
        assert url == "http://127.0.0.1:9999"
        assert worker.active_run_id == "run-1"
        assert worker.browser_state == "ready"


def test_request_browser_start_rolls_back_lease_on_timeout() -> None:
    registry = WorkerRegistry()
    loop = MagicMock()
    worker = WorkerConnection(user_id="user-1", websocket=MagicMock(), loop=loop)
    registry.register(worker)

    with (
        patch.object(WorkerRegistry, "_teardown_proxy"),
        patch.object(workers.CdpProxy, "start", return_value="http://127.0.0.1:9999"),
    ):
        with pytest.raises(TimeoutError):
            registry.request_browser_start(
                "user-1",
                run_id="run-1",
                fresh_profile=True,
                timeout=0.2,
            )
        assert worker.browser_state == "idle"
        assert worker.active_run_id is None


def test_browser_stopped_uses_lease_lock() -> None:
    registry = WorkerRegistry()
    loop = MagicMock()
    worker = WorkerConnection(user_id="user-1", websocket=MagicMock(), loop=loop)
    registry.register(worker)
    worker.browser_state = "ready"
    worker.active_run_id = "run-1"
    with patch.object(WorkerRegistry, "_teardown_proxy") as teardown:
        registry.handle_control_message(worker, {"type": "browser.stopped"})
        teardown.assert_called_once()
    assert worker.browser_state == "idle"
    assert worker.active_run_id is None


def test_detach_cdp_proxy_keeps_browser_lease() -> None:
    """Proxy mux stops before Playwright cleanup; Chrome stop is a separate step."""
    registry = WorkerRegistry()
    loop = MagicMock()
    worker = WorkerConnection(user_id="user-1", websocket=MagicMock(), loop=loop)
    registry.register(worker)
    worker.browser_state = "ready"
    worker.active_run_id = "run-1"
    worker.cdp_url = "http://127.0.0.1:9999"
    with patch.object(WorkerRegistry, "_teardown_proxy") as teardown:
        registry.detach_cdp_proxy("user-1", run_id="run-1")
        teardown.assert_called_once()
    assert worker.browser_state == "ready"
    assert worker.active_run_id == "run-1"
    assert worker.cdp_url is None


def test_runner_detaches_proxy_before_playwright_cleanup() -> None:
    from pathlib import Path

    runner_src = (
        Path(__file__).resolve().parents[1] / "src/smart_automator/server/runner.py"
    ).read_text(encoding="utf-8")
    detach = runner_src.index("detach_cdp_proxy")
    cleanup = runner_src.index("executor.cleanup()")
    stop = runner_src.index("request_browser_stop(")
    assert detach < cleanup < stop


def test_connect_cdp_eof_does_not_kill_control_wss() -> None:
    """Regression: CDP peer close must drop the channel only, not the control WSS."""
    from pathlib import Path

    worker_ws = (
        Path(__file__).resolve().parents[1]
        / "apps/smart-automator-connect/src/worker_ws.c"
    ).read_text(encoding="utf-8")
    pump = worker_ws.split("static int pump_cdp_channel(", 1)[1].split(
        "static int pump_cdp_reads(", 1
    )[0]
    assert "close_channel(ws, ch);" in pump
    assert "CDP peer closed" in pump or "keep control WSS" in pump
    # After closing the channel on recv failure, do not propagate -1 as WSS death.
    eof_branch = pump.split("if (n < 0)", 1)[1].split("if (n == 0)", 1)[0]
    assert "return 0;" in eof_branch
    assert "return -1;" not in eof_branch


def test_probe_helpers_removed_from_production_path() -> None:
    assert not hasattr(WorkerRegistry, "_probe_cdp_http_rtt")
    from smart_automator.browser.context import BrowserContext
    import inspect

    assert "_probe_evaluate_rtt" not in inspect.getsource(BrowserContext)


def test_connect_cancel_not_cleared_inside_chrome_start() -> None:
    """Regression: sa_chrome_start must not wipe in-flight cancel."""
    from pathlib import Path

    chrome_c = Path(__file__).resolve().parents[1] / "apps/smart-automator-connect/src/chrome.c"
    runtime_c = Path(__file__).resolve().parents[1] / "apps/smart-automator-connect/src/runtime.c"
    chrome_src = chrome_c.read_text(encoding="utf-8")
    runtime_src = runtime_c.read_text(encoding="utf-8")

    # Extract sa_chrome_start body (until next top-level function).
    start = chrome_src.index("int sa_chrome_start(")
    end = chrome_src.index("\nstatic int wait_for_port_closed", start)
    assert "sa_chrome_clear_cancel" not in chrome_src[start:end]
    assert "sa_chrome_clear_cancel();" in runtime_src
    assert "reap_chrome_after_cancel" in runtime_src
    assert "SA_CHROME_REAP_WAIT_MS" in runtime_src
    assert "SA_RECONNECT_STABLE_MS" in runtime_src


def test_connect_tls_verify_and_safe_disconnect() -> None:
    """Regression: peer verify enabled; UI disconnect interrupts without SSL_free race."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "apps/smart-automator-connect/src"
    worker_ws = (root / "worker_ws.c").read_text(encoding="utf-8")
    tls_http = (root / "tls_http.c").read_text(encoding="utf-8")
    runtime = (root / "runtime.c").read_text(encoding="utf-8")
    app = (root / "app.c").read_text(encoding="utf-8")

    assert "SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER, NULL)" in worker_ws
    assert "SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER, NULL)" in tls_http
    assert "SMART_AUTOMATOR_INSECURE_TLS" in worker_ws
    assert "void sa_worker_ws_interrupt" in worker_ws or "sa_worker_ws_interrupt(sa_worker_ws_t" in worker_ws
    disconnect = runtime.split("void sa_runtime_disconnect", 1)[1].split("\nint sa_runtime_is_busy", 1)[0]
    assert "sa_worker_ws_interrupt(rt->ws)" in disconnect
    assert "pthread_join(rt->thread" in disconnect
    # Interrupt first; close only after the WSS thread has joined.
    assert disconnect.index("sa_worker_ws_interrupt") < disconnect.index("pthread_join(rt->thread")
    assert disconnect.index("pthread_join(rt->thread") < disconnect.index("sa_worker_ws_close(rt->ws)")
    assert '\\"type\\": \\"ping\\"' in runtime
    assert "append_json_escaped(msg, sizeof(msg), raw)" in runtime
    assert "click Reconnect to retry" in runtime
    assert "on_reconnect_clicked" in app
    assert "Reconnect" in app


def test_win32_deadline_send_preserves_nonblock_intent() -> None:
    from pathlib import Path

    net_c = (
        Path(__file__).resolve().parents[1] / "apps/smart-automator-connect/src/net.c"
    ).read_text(encoding="utf-8")
    assert "was_nonblock = 1;" in net_c
    assert "Winsock cannot query FIONBIO" in net_c
    assert "leave them nonblocking" in net_c
