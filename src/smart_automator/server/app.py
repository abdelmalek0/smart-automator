"""
FastAPI backend for the Smart Automator UI.

Run from the project root:
    uv run smart-automator-api
"""

from __future__ import annotations

import asyncio
import logging
import logging.config
import os
import threading
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..storage.websites import WebsiteStore, task_to_api_dict, website_to_api_dict
from ..browser.chrome_profiles import discover_chrome_profiles
from .auth import auth_router, get_current_user
from .auth.dependencies import SESSION_COOKIE_NAME, resolve_user_from_session
from .auth.stores import User
from .config_service import (
    apply_config_update,
    build_config_response,
    check_llm_connection,
    load_pricing,
    save_pricing,
)
from .models import (
    ConfigUpdate,
    PricingEntryModel,
    StartRunRequest,
    WebsiteCreateRequest,
    WebsiteTaskCreateRequest,
    WebsiteTaskUpdateRequest,
    WebsiteUpdateRequest,
)
from .paths import AUTH_DIR, ENV_FILE, HISTORY_DIR, REPLAY_DIR, REPORT_DIR, RUNS_DIR, SCREENSHOT_DIR, UI_DIST, WEBSITES_DIR
from .run_store import user_owns_run_prefix
from .history_store import delete_run_history
from .replay_store import delete_run_replay, has_replay_script, load_run_replay
from .run_state import (
    RunState,
    add_run,
    delete_run_for_user,
    get_run_for_user,
    list_runs_for_user,
)
from .runner import run_automation
from .step_mapper import compose_agent_task
from .tools import list_action_tools

load_dotenv(ENV_FILE)

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s %(levelname)-8s %(name)s  %(message)s",
                "datefmt": "%H:%M:%S",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            }
        },
        "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
        "loggers": {
            "uvicorn": {"level": "WARNING"},
            "uvicorn.error": {"level": "WARNING"},
            "uvicorn.access": {"level": "WARNING"},
            "websockets": {"level": "WARNING"},
        },
    }
)

log = logging.getLogger(__name__)

app = FastAPI(title="Smart Automator", version="0.1.0")

_cors_origins_env = os.getenv("CORS_ORIGINS", "")
_cors_origins: list[str] = (
    [origin.strip() for origin in _cors_origins_env.split(",") if origin.strip()]
    if _cors_origins_env
    else [
        "http://localhost:5173",
        "http://localhost:8400",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8400",
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
REPLAY_DIR.mkdir(parents=True, exist_ok=True)
AUTH_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)
WEBSITES_DIR.mkdir(parents=True, exist_ok=True)

app.include_router(auth_router)


def _websites(user: User) -> WebsiteStore:
    return WebsiteStore(user.id)


def _require_owned_run(user: User, run_id: str) -> RunState:
    run = get_run_for_user(user.id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.post("/api/runs", status_code=201)
async def start_run(req: StartRunRequest, user: User = Depends(get_current_user)):
    run_id = str(uuid.uuid4())
    display_task = req.task.strip()
    if not display_task:
        raise HTTPException(status_code=400, detail="Task is required")
    success_criteria = req.success_criteria.strip()
    if not success_criteria:
        raise HTTPException(status_code=400, detail="Success criteria is required")
    if req.use_replay_script:
        if not req.source_run_id:
            raise HTTPException(
                status_code=400,
                detail="source_run_id is required when use_replay_script is true",
            )
        if get_run_for_user(user.id, req.source_run_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Source run not found: {req.source_run_id}",
            )
        if load_run_replay(req.source_run_id) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Replay script not found for source run {req.source_run_id}",
            )
        source_run_id = req.source_run_id
    elif req.source_run_id:
        if get_run_for_user(user.id, req.source_run_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Source run not found: {req.source_run_id}",
            )
        source_run_id = req.source_run_id
    else:
        source_run_id = None

    test_name = req.name.strip() if req.name else None
    effective_task = display_task
    website_id = req.website_id
    website_task_id = req.website_task_id
    if website_task_id:
        if not website_id:
            raise HTTPException(
                status_code=400,
                detail="website_id is required when website_task_id is set",
            )
        website = _websites(user).get_website(website_id)
        if not website:
            raise HTTPException(status_code=404, detail="Website not found")
        if not any(task.id == website_task_id for task in website.tasks):
            raise HTTPException(status_code=404, detail="Website task not found")
    elif website_id:
        website = _websites(user).get_website(website_id)
        if not website:
            raise HTTPException(status_code=404, detail="Website not found")
    if website_id:
        effective_task = compose_agent_task(
            display_task,
            name=website.name,
            url=website.url,
            context_prompt=website.context_prompt,
            test_name=test_name,
        )
    else:
        effective_task = compose_agent_task(
            display_task,
            name="",
            url="",
            context_prompt="",
            test_name=test_name,
        )

    run = RunState(
        run_id=run_id,
        user_id=user.id,
        task=display_task,
        headless=req.headless,
        max_steps=req.max_steps,
        success_criteria=success_criteria,
        website_id=website_id,
        effective_task=effective_task,
        cdp_url=req.cdp_url,
        fresh_profile=req.fresh_profile,
        name=test_name,
        source_run_id=source_run_id,
        use_replay_script=req.use_replay_script,
        website_task_id=website_task_id,
    )
    run._loop = asyncio.get_event_loop()
    add_run(run)
    run.persist(has_replay_script=has_replay_script(run.run_id))

    thread = threading.Thread(target=run_automation, args=(run,), daemon=True)
    thread.start()
    return run.to_summary(has_replay_script=has_replay_script(run.run_id))


@app.get("/api/runs")
async def api_list_runs(user: User = Depends(get_current_user)):
    return [
        run.to_summary(has_replay_script=has_replay_script(run.run_id))
        for run in list_runs_for_user(user.id)
    ]


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str, user: User = Depends(get_current_user)):
    run = _require_owned_run(user, run_id)
    return run.to_dict(has_replay_script=has_replay_script(run_id))


@app.get("/api/runs/{run_id}/report")
async def download_report(run_id: str, user: User = Depends(get_current_user)):
    run = _require_owned_run(user, run_id)
    report_file: Path | None = None
    if run.report_path:
        candidate = Path(run.report_path)
        if candidate.is_file():
            report_file = candidate
    if report_file is None:
        candidate = REPORT_DIR / f"{run_id}.html"
        if candidate.is_file():
            report_file = candidate
    if report_file is None:
        raise HTTPException(status_code=404, detail="Report not yet available")
    return FileResponse(
        report_file,
        media_type="text/html",
        filename=f"run-{run_id[:8]}.html",
    )


def _cancel_active_run(run: RunState) -> None:
    if run.status not in ("pending", "running", "awaiting_human"):
        return
    log.info("DELETE /api/runs/%s — cancelling", run.run_id[:8])
    run._cancelled.set()
    if run.executor is not None:
        run.executor.cancel()
    run.status = "cancelled"
    run.finished_at = time.time()
    run.broadcast({"type": "status", "status": "cancelled"})
    run.broadcast({"type": "closed"})
    try:
        from .replay_store import has_replay_script as _has_replay

        run.persist(has_replay_script=_has_replay(run.run_id))
    except Exception:
        log.debug("Failed to persist cancelled run %s", run.run_id[:8], exc_info=True)


def _purge_run_artifacts(run_id: str, *, report_path: str | None = None) -> None:
    delete_run_history(run_id)
    delete_run_replay(run_id)

    report_candidates = [REPORT_DIR / f"{run_id}.html"]
    if report_path:
        report_candidates.append(Path(report_path))
    for path in report_candidates:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass

    prefix = f"{run_id[:8]}_step_"
    try:
        for path in SCREENSHOT_DIR.glob(f"{prefix}*.png"):
            path.unlink(missing_ok=True)
    except OSError:
        pass


@app.delete("/api/runs/{run_id}")
async def cancel_run(run_id: str, purge: bool = False, user: User = Depends(get_current_user)):
    run = _require_owned_run(user, run_id)
    if purge:
        report_path = run.report_path
        _cancel_active_run(run)
        _websites(user).clear_last_trained_run_id(run_id)
        delete_run_for_user(user.id, run_id)
        _purge_run_artifacts(run_id, report_path=report_path)
        log.info("DELETE /api/runs/%s — purged", run_id[:8])
        return {"ok": True}
    if run.status not in ("pending", "running", "awaiting_human"):
        return {"ok": True}
    _cancel_active_run(run)
    return {"ok": True}


def _hitl_unavailable_reason(run) -> str | None:
    if run.headless:
        return "Human-in-the-loop is disabled for headless runs"
    if run.use_replay_script:
        return "Human-in-the-loop is disabled for automatic replay runs"
    return None


@app.post("/api/runs/{run_id}/take-control")
async def take_control(run_id: str, user: User = Depends(get_current_user)):
    run = _require_owned_run(user, run_id)
    unavailable = _hitl_unavailable_reason(run)
    if unavailable:
        raise HTTPException(status_code=400, detail=unavailable)
    if run.status not in ("running", "awaiting_human", "pending"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot take control while run status is {run.status}",
        )
    if run.executor is None:
        raise HTTPException(status_code=400, detail="Run executor is not active")
    ok, error = await asyncio.to_thread(
        run.executor.submit_hitl_command,
        "take_control",
        source="manual",
        wait=False,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=error or "Failed to take control")
    return {"ok": True, "human_controlling": run.human_controlling, "pending": True}


@app.post("/api/runs/{run_id}/return-control")
async def return_control(run_id: str, user: User = Depends(get_current_user)):
    run = _require_owned_run(user, run_id)
    unavailable = _hitl_unavailable_reason(run)
    if unavailable:
        raise HTTPException(status_code=400, detail=unavailable)
    if run.executor is None:
        raise HTTPException(status_code=400, detail="Run executor is not active")
    ok, error = await asyncio.to_thread(
        run.executor.submit_hitl_command,
        "return_control",
    )
    if not ok:
        raise HTTPException(status_code=400, detail=error or "Failed to return control")
    run.human_controlling = False
    return {"ok": True, "human_controlling": False}


async def _safe_ws_send_json(websocket: WebSocket, payload: dict) -> bool:
    try:
        await websocket.send_json(payload)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


@app.get("/api/websites")
async def api_list_websites(user: User = Depends(get_current_user)):
    return [website_to_api_dict(website) for website in _websites(user).list_websites()]


@app.post("/api/websites", status_code=201)
async def create_website(req: WebsiteCreateRequest, user: User = Depends(get_current_user)):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    website = _websites(user).create_website(req.name, req.url, req.context_prompt)
    return website_to_api_dict(website)


@app.get("/api/websites/{website_id}")
async def api_get_website(website_id: str, user: User = Depends(get_current_user)):
    website = _websites(user).get_website(website_id)
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    return website_to_api_dict(website)


@app.put("/api/websites/{website_id}")
async def update_website(
    website_id: str,
    req: WebsiteUpdateRequest,
    user: User = Depends(get_current_user),
):
    website = _websites(user).update_website(
        website_id,
        name=req.name,
        url=req.url,
        context_prompt=req.context_prompt,
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    return website_to_api_dict(website)


@app.delete("/api/websites/{website_id}")
async def delete_website(website_id: str, user: User = Depends(get_current_user)):
    if not _websites(user).delete_website(website_id):
        raise HTTPException(status_code=404, detail="Website not found")
    return {"ok": True}


@app.post("/api/websites/{website_id}/tasks", status_code=201)
async def create_website_task(
    website_id: str,
    req: WebsiteTaskCreateRequest,
    user: User = Depends(get_current_user),
):
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="Task is required")
    if not req.success_criteria.strip():
        raise HTTPException(status_code=400, detail="Success criteria is required")
    task = _websites(user).add_task(
        website_id,
        task=req.task,
        success_criteria=req.success_criteria,
        name=req.name,
        headless=req.headless,
        max_steps=req.max_steps,
        cdp_url=req.cdp_url,
        fresh_profile=req.fresh_profile,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Website not found")
    return task_to_api_dict(task, user_id=user.id)


@app.put("/api/websites/{website_id}/tasks/{task_id}")
async def update_website_task(
    website_id: str,
    task_id: str,
    req: WebsiteTaskUpdateRequest,
    user: User = Depends(get_current_user),
):
    task = _websites(user).update_task(
        website_id,
        task_id,
        task=req.task,
        success_criteria=req.success_criteria,
        name=req.name,
        headless=req.headless,
        max_steps=req.max_steps,
        cdp_url=req.cdp_url,
        fresh_profile=req.fresh_profile,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Website or task not found")
    return task_to_api_dict(task, user_id=user.id)


@app.delete("/api/websites/{website_id}/tasks/{task_id}")
async def delete_website_task(website_id: str, task_id: str, user: User = Depends(get_current_user)):
    if not _websites(user).delete_task(website_id, task_id):
        raise HTTPException(status_code=404, detail="Website or task not found")
    return {"ok": True}


@app.get("/api/tools")
async def api_list_tools(user: User = Depends(get_current_user)):
    return list_action_tools()


@app.get("/api/config")
async def api_get_config(user: User = Depends(get_current_user)):
    return build_config_response()


@app.get("/api/chrome-profiles")
async def api_list_chrome_profiles(user: User = Depends(get_current_user)):
    return [profile.to_dict() for profile in discover_chrome_profiles()]


@app.put("/api/config")
async def api_update_config(update: ConfigUpdate, user: User = Depends(get_current_user)):
    return apply_config_update(update)


@app.post("/api/config/check")
async def api_check_config(update: ConfigUpdate | None = None, user: User = Depends(get_current_user)):
    try:
        check_llm_connection(update)
        return {"ok": True}
    except BaseException as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/pricing")
async def api_get_pricing(user: User = Depends(get_current_user)):
    return load_pricing()


@app.put("/api/pricing")
async def api_save_pricing(entries: list[PricingEntryModel], user: User = Depends(get_current_user)):
    count = save_pricing([entry.model_dump() for entry in entries])
    return {"ok": True, "count": count}


@app.get("/screenshots/{filename}")
async def serve_screenshot(filename: str, user: User = Depends(get_current_user)):
    if "/" in filename or ".." in filename or not filename.endswith(".png"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    prefix = filename.split("_step_", maxsplit=1)[0]
    if not user_owns_run_prefix(user.id, prefix):
        raise HTTPException(status_code=404, detail="Screenshot not found")
    path = SCREENSHOT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path, media_type="image/png")


@app.websocket("/ws/runs/{run_id}")
async def ws_run_stream(websocket: WebSocket, run_id: str):
    session_id = websocket.cookies.get(SESSION_COOKIE_NAME)
    user = resolve_user_from_session(session_id)
    await websocket.accept()
    if user is None:
        await websocket.close(code=1008)
        return

    run = get_run_for_user(user.id, run_id)
    if not run:
        await websocket.send_json({"type": "error", "message": "Run not found"})
        await websocket.close()
        return

    queue = run.subscribe()
    try:
        if not await _safe_ws_send_json(websocket, {"type": "snapshot", "run": run.to_dict()}):
            return
        if run.status not in ("pending", "running", "awaiting_human"):
            await _safe_ws_send_json(websocket, {"type": "closed"})
            await websocket.close()
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                if not await _safe_ws_send_json(websocket, {"type": "ping"}):
                    break
                continue
            if not await _safe_ws_send_json(websocket, event):
                break
            if event.get("type") == "closed":
                break
    except WebSocketDisconnect:
        log.debug("WS disconnect run=%s", run_id[:8])
    finally:
        run.unsubscribe(queue)


if UI_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(UI_DIST / "assets")),
        name="assets",
    )

    @app.get("/", response_class=HTMLResponse)
    async def serve_root():
        return (UI_DIST / "index.html").read_text(encoding="utf-8")

    @app.get("/{path:path}", response_class=HTMLResponse)
    async def serve_spa(path: str):
        if path.startswith(("api/", "ws/", "screenshots/")):
            raise HTTPException(status_code=404)
        index = UI_DIST / "index.html"
        if index.exists():
            return index.read_text(encoding="utf-8")
        raise HTTPException(status_code=404)


def main() -> None:
    import uvicorn
    from pathlib import Path

    # Only watch package source. Writing under data/ (histories, reports, replays/*.py)
    # must not restart the process — that wipes in-memory run history in the sidebar.
    package_dir = str(Path(__file__).resolve().parent.parent)

    uvicorn.run(
        "smart_automator.server.app:app",
        host="0.0.0.0",
        port=8400,
        reload=True,
        reload_dirs=[package_dir],
        reload_excludes=[
            "**/__pycache__/**",
            "**/*.pyc",
            "**/data/**",
        ],
    )


if __name__ == "__main__":
    main()
