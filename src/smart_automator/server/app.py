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
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..storage.websites import WebsiteStore
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
from .paths import ENV_FILE, HISTORY_DIR, REPLAY_DIR, REPORT_DIR, SCREENSHOT_DIR, UI_DIST
from .history_store import load_run_history
from .replay_store import load_run_replay
from .run_state import RunState, add_run, get_run, list_runs
from .runner import run_automation
from .step_mapper import compose_task
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
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
REPLAY_DIR.mkdir(parents=True, exist_ok=True)

_website_store: WebsiteStore | None = None


def _websites() -> WebsiteStore:
    global _website_store
    if _website_store is None:
        _website_store = WebsiteStore()
    return _website_store


@app.post("/api/runs", status_code=201)
async def start_run(req: StartRunRequest):
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
        if load_run_replay(req.source_run_id) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Replay script not found for source run {req.source_run_id}",
            )
        source_run_id = req.source_run_id
    elif req.source_run_id:
        if load_run_history(req.source_run_id) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Replay history not found for source run {req.source_run_id}",
            )
        source_run_id = req.source_run_id
    else:
        source_run_id = None

    test_name = req.name.strip() if req.name else None
    effective_task = display_task
    website_id = req.website_id
    if website_id:
        website = _websites().get_website(website_id)
        if not website:
            raise HTTPException(status_code=404, detail="Website not found")
        effective_task = compose_task(
            display_task,
            name=website.name,
            url=website.url,
            context_prompt=website.context_prompt,
            success_criteria=success_criteria,
            test_name=test_name,
        )
    else:
        effective_task = compose_task(
            display_task,
            name="",
            url="",
            context_prompt="",
            success_criteria=success_criteria,
            test_name=test_name,
        )

    run = RunState(
        run_id=run_id,
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
    )
    run._loop = asyncio.get_event_loop()
    add_run(run)

    thread = threading.Thread(target=run_automation, args=(run,), daemon=True)
    thread.start()
    return run.to_summary()


@app.get("/api/runs")
async def api_list_runs():
    return [run.to_summary() for run in reversed(list_runs())]


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict()


@app.get("/api/runs/{run_id}/report")
async def download_report(run_id: str):
    run = get_run(run_id)
    if not run or not run.report_path:
        raise HTTPException(status_code=404, detail="Report not yet available")
    report_file = Path(run.report_path)
    if not report_file.is_file():
        candidate = REPORT_DIR / f"{run_id}.html"
        if candidate.is_file():
            report_file = candidate
        else:
            raise HTTPException(status_code=404, detail="Report not yet available")
    return FileResponse(
        report_file,
        media_type="text/html",
        filename=f"run-{run_id[:8]}.html",
    )


@app.delete("/api/runs/{run_id}")
async def cancel_run(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ("pending", "running"):
        return {"ok": True}
    log.info("DELETE /api/runs/%s — cancelling", run_id[:8])
    run._cancelled.set()
    if run.executor is not None:
        run.executor.cancel()
    run.status = "cancelled"
    run.finished_at = time.time()
    run.broadcast({"type": "status", "status": "cancelled"})
    run.broadcast({"type": "closed"})
    return {"ok": True}


@app.get("/api/websites")
async def api_list_websites():
    return [website.to_dict() for website in _websites().list_websites()]


@app.post("/api/websites", status_code=201)
async def create_website(req: WebsiteCreateRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    website = _websites().create_website(req.name, req.url, req.context_prompt)
    return website.to_dict()


@app.get("/api/websites/{website_id}")
async def api_get_website(website_id: str):
    website = _websites().get_website(website_id)
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    return website.to_dict()


@app.put("/api/websites/{website_id}")
async def update_website(website_id: str, req: WebsiteUpdateRequest):
    website = _websites().update_website(
        website_id,
        name=req.name,
        url=req.url,
        context_prompt=req.context_prompt,
    )
    if not website:
        raise HTTPException(status_code=404, detail="Website not found")
    return website.to_dict()


@app.delete("/api/websites/{website_id}")
async def delete_website(website_id: str):
    if not _websites().delete_website(website_id):
        raise HTTPException(status_code=404, detail="Website not found")
    return {"ok": True}


@app.post("/api/websites/{website_id}/tasks", status_code=201)
async def create_website_task(website_id: str, req: WebsiteTaskCreateRequest):
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="Task is required")
    if not req.success_criteria.strip():
        raise HTTPException(status_code=400, detail="Success criteria is required")
    task = _websites().add_task(
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
    return task.to_dict()


@app.put("/api/websites/{website_id}/tasks/{task_id}")
async def update_website_task(website_id: str, task_id: str, req: WebsiteTaskUpdateRequest):
    task = _websites().update_task(
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
    return task.to_dict()


@app.delete("/api/websites/{website_id}/tasks/{task_id}")
async def delete_website_task(website_id: str, task_id: str):
    if not _websites().delete_task(website_id, task_id):
        raise HTTPException(status_code=404, detail="Website or task not found")
    return {"ok": True}


@app.get("/api/tools")
async def api_list_tools():
    return list_action_tools()


@app.get("/api/config")
async def api_get_config():
    return build_config_response()


@app.put("/api/config")
async def api_update_config(update: ConfigUpdate):
    return apply_config_update(update)


@app.post("/api/config/check")
async def api_check_config(update: ConfigUpdate | None = None):
    try:
        check_llm_connection(update)
        return {"ok": True}
    except BaseException as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/pricing")
async def api_get_pricing():
    return load_pricing()


@app.put("/api/pricing")
async def api_save_pricing(entries: list[PricingEntryModel]):
    count = save_pricing([entry.model_dump() for entry in entries])
    return {"ok": True, "count": count}


@app.get("/screenshots/{filename}")
async def serve_screenshot(filename: str):
    if "/" in filename or ".." in filename or not filename.endswith(".png"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = SCREENSHOT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path, media_type="image/png")


@app.websocket("/ws/runs/{run_id}")
async def ws_run_stream(websocket: WebSocket, run_id: str):
    await websocket.accept()
    run = get_run(run_id)
    if not run:
        await websocket.send_json({"type": "error", "message": "Run not found"})
        await websocket.close()
        return

    queue = run.subscribe()
    try:
        await websocket.send_json({"type": "snapshot", "run": run.to_dict()})
        if run.status not in ("pending", "running"):
            await websocket.send_json({"type": "closed"})
            await websocket.close()
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            await websocket.send_json(event)
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
