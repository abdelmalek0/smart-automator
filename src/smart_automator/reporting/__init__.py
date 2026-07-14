from __future__ import annotations

from pathlib import Path
from typing import Any

from ..agent.history import AgentStepHistory
from ..server.paths import REPORT_DIR
from ..server.run_state import RunState
from .builder import build_report_data
from .html_report import render_html_report


def generate_run_report(
    run: RunState,
    history: AgentStepHistory,
    *,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    planner_model: str | None = None,
    failed_actions: list[dict[str, Any]] | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Generate a self-contained HTML report for a finished run."""
    report_dir = output_dir or REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)

    data = build_report_data(
        run,
        history,
        llm_provider=llm_provider,
        llm_model=llm_model,
        planner_model=planner_model,
        failed_actions=failed_actions,
    )
    html_content = render_html_report(data)
    report_path = report_dir / f"{run.run_id}.html"
    report_path.write_text(html_content, encoding="utf-8")
    return report_path
