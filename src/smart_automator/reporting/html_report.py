from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _status_class(status: str) -> str:
    if status in ("pass", "verified"):
        return "status-pass"
    if status in ("fail", "error", "failed"):
        return "status-fail"
    if status in ("cancelled", "no_effect", "unverified"):
        return "status-warn"
    return ""


def _fmt_time(epoch: float | None) -> str:
    if epoch is None:
        return "—"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_cost(cost: float | None) -> str:
    if cost is None:
        return "—"
    return f"${cost:.4f}"


def _render_metadata(data: dict[str, Any]) -> str:
    llm = data.get("llm") or {}
    rows = [
        ("Run ID", data.get("run_id")),
        ("Status", data.get("status")),
        ("Website ID", data.get("website_id") or "—"),
        ("Headless", "yes" if data.get("headless") else "no"),
        ("Max steps", data.get("max_steps")),
        ("CDP URL", data.get("cdp_url") or "—"),
        ("Fresh profile", "yes" if data.get("fresh_profile") else "no"),
        ("Started", _fmt_time(data.get("started_at"))),
        ("Finished", _fmt_time(data.get("finished_at"))),
        ("LLM provider", llm.get("provider") or "—"),
        ("Navigator model", llm.get("model") or "—"),
        ("Planner model", llm.get("planner_model") or llm.get("model") or "—"),
    ]
    return "\n".join(
        f"<tr><th>{_esc(label)}</th><td>{_esc(value)}</td></tr>"
        for label, value in rows
    )


def _render_stats(data: dict[str, Any]) -> str:
    tokens = data.get("tokens") or {}
    timing = data.get("turn_timing") or {}
    return f"""
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Duration</div>
        <div class="stat-value">{_esc(data.get("duration_label"))}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Steps</div>
        <div class="stat-value">{len(data.get("steps") or [])}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Total tokens</div>
        <div class="stat-value">{tokens.get("total", 0):,}</div>
        <div class="stat-sub">prompt {tokens.get("prompt", 0):,} · completion {tokens.get("completion", 0):,}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Est. cost</div>
        <div class="stat-value">{_esc(_fmt_cost(tokens.get("cost_usd")))}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Step time (sum)</div>
        <div class="stat-value">{(data.get("step_elapsed_ms") or 0) / 1000:.1f}s</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Last turn timing</div>
        <div class="stat-value">{timing.get("turn_ms") or "—"} ms</div>
        <div class="stat-sub">DOM {timing.get("snapshot_ms") or "—"} · LLM {timing.get("llm_navigator_ms") or "—"} ms</div>
      </div>
    </div>
    """


def _render_steps(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return '<p class="muted">No steps recorded.</p>'
    blocks: list[str] = []
    for step in steps:
        status = step.get("status", "")
        screenshot = step.get("screenshot_url")
        img_html = ""
        if screenshot:
            img_html = f'<img class="step-screenshot" src="{_esc(screenshot)}" alt="Step {step.get("index")} screenshot" />'
        args_json = json.dumps(step.get("args") or {}, indent=2, default=str)
        blocks.append(
            f"""
            <article class="step-card">
              <header>
                <span class="step-index">Step {step.get("index")}</span>
                <span class="badge {_status_class(status)}">{_esc(status)}</span>
                <span class="step-elapsed">{step.get("elapsed_ms", 0)} ms</span>
              </header>
              <p class="step-thought">{_esc(step.get("thought"))}</p>
              <p><strong>Action:</strong> <code>{_esc(step.get("action"))}</code></p>
              <details>
                <summary>Args</summary>
                <pre>{_esc(args_json)}</pre>
              </details>
              <p><strong>Result:</strong> {_esc(step.get("result"))}</p>
              {img_html}
            </article>
            """
        )
    return "\n".join(blocks)


def _render_element(element: dict[str, Any] | None) -> str:
    if not element:
        return '<span class="muted">—</span>'
    attrs = element.get("attributes") or {}
    attr_lines = ", ".join(f"{_esc(k)}={_esc(v)}" for k, v in list(attrs.items())[:6])
    return f"""
    <div class="element-block">
      <div><strong>{_esc(element.get("tagName"))}</strong> [{_esc(element.get("highlightIndex"))}]</div>
      <div class="mono xpath">{_esc(element.get("xpath"))}</div>
      {f'<div class="mono css">{_esc(element.get("cssSelector"))}</div>' if element.get("cssSelector") else ""}
      {f'<div class="attrs">{attr_lines}</div>' if attr_lines else ""}
    </div>
    """


def _render_action_timeline(timeline: list[dict[str, Any]]) -> str:
    if not timeline:
        return '<p class="muted">No DOM/XPath actions recorded.</p>'
    rows: list[str] = []
    for entry in timeline:
        status = entry.get("verification_status") or ("pass" if entry.get("success") else "fail")
        if entry.get("error"):
            status = "error"
        rows.append(
            f"""
            <tr>
              <td>{entry.get("step")}.{entry.get("action_num")}</td>
              <td><code>{_esc(entry.get("action"))}</code></td>
              <td class="mono">{_esc(json.dumps(entry.get("args") or {}, default=str))}</td>
              <td class="url-cell">{_esc(entry.get("url"))}</td>
              <td>{_render_element(entry.get("element"))}</td>
              <td><span class="badge {_status_class(status)}">{_esc(status)}</span></td>
              <td>{_esc(entry.get("verification_evidence") or entry.get("extracted_content") or entry.get("error"))}</td>
            </tr>
            """
        )
    return f"""
    <div class="table-wrap">
      <table class="timeline-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Action</th>
            <th>Args</th>
            <th>Page URL</th>
            <th>DOM / XPath</th>
            <th>Verification</th>
            <th>Outcome</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows)}
        </tbody>
      </table>
    </div>
    """


def _render_plan(plan: dict[str, Any]) -> str:
    if not plan:
        return ""
    completed = plan.get("completed") or []
    remaining = plan.get("remaining") or []
    in_progress = plan.get("in_progress")
    parts = ["<section><h2>Plan</h2>"]
    if completed:
        parts.append("<h3>Completed</h3><ul>")
        parts.extend(f"<li>{_esc(item)}</li>" for item in completed)
        parts.append("</ul>")
    if in_progress:
        parts.append(f"<h3>In progress</h3><p>{_esc(in_progress)}</p>")
    if remaining:
        parts.append("<h3>Remaining</h3><ul>")
        parts.extend(f"<li>{_esc(item)}</li>" for item in remaining)
        parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def _render_replay_script(data: dict[str, Any]) -> str:
    script = data.get("replay_script") or ""
    if not script.strip():
        return '<p class="muted">No replayable actions recorded.</p>'
    return f"""
    <section>
      <h2>Replay Code</h2>
      <p class="muted">Copy-paste Playwright Python script for LLM-free replay.</p>
      <div class="code-block">
        <pre><code class="language-python">{_esc(script)}</code></pre>
      </div>
    </section>
    """


def render_html_report(data: dict[str, Any]) -> str:
    status = data.get("status", "unknown")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Run Report — {_esc(data.get("run_id", "")[:8])}</title>
  <style>
    :root {{
      --bg: #0f1117;
      --surface: #171a22;
      --border: #2a2f3a;
      --text: #e8eaed;
      --muted: #9aa0a6;
      --pass: #34a853;
      --fail: #ea4335;
      --warn: #fbbc04;
      --accent: #8ab4f8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 2rem;
    }}
    h1, h2, h3 {{ margin-top: 0; }}
    h1 {{ font-size: 1.75rem; }}
    h2 {{ font-size: 1.25rem; margin: 2rem 0 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 1rem;
      flex-wrap: wrap;
      margin-bottom: 1.5rem;
    }}
    .badge {{
      display: inline-block;
      padding: 0.15rem 0.55rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      background: var(--border);
    }}
    .status-pass {{ background: rgba(52,168,83,0.2); color: var(--pass); }}
    .status-fail {{ background: rgba(234,67,53,0.2); color: var(--fail); }}
    .status-warn {{ background: rgba(251,188,4,0.15); color: var(--warn); }}
    .summary-box {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1rem 1.25rem;
      margin-bottom: 1.5rem;
    }}
    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1.5rem;
    }}
    .stat-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.85rem 1rem;
    }}
    .stat-label {{ color: var(--muted); font-size: 0.8rem; }}
    .stat-value {{ font-size: 1.35rem; font-weight: 700; margin-top: 0.15rem; }}
    .stat-sub {{ color: var(--muted); font-size: 0.75rem; margin-top: 0.25rem; }}
    table.meta {{ border-collapse: collapse; width: 100%; max-width: 720px; }}
    table.meta th, table.meta td {{
      text-align: left;
      padding: 0.4rem 0.75rem 0.4rem 0;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }}
    table.meta th {{ color: var(--muted); width: 180px; font-weight: 500; }}
    .task {{ color: var(--accent); white-space: pre-wrap; }}
    .step-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1rem;
      margin-bottom: 1rem;
    }}
    .step-card header {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 0.5rem;
    }}
    .step-index {{ font-weight: 700; }}
    .step-elapsed {{ margin-left: auto; color: var(--muted); font-size: 0.85rem; }}
    .step-thought {{ color: var(--muted); font-style: italic; }}
    .step-screenshot {{
      max-width: 100%;
      border-radius: 6px;
      border: 1px solid var(--border);
      margin-top: 0.75rem;
    }}
    .table-wrap {{ overflow-x: auto; }}
    .timeline-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }}
    .timeline-table th, .timeline-table td {{
      border: 1px solid var(--border);
      padding: 0.5rem 0.65rem;
      vertical-align: top;
    }}
    .timeline-table th {{
      background: var(--surface);
      text-align: left;
      color: var(--muted);
    }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.8rem; word-break: break-all; }}
    .xpath {{ color: #c58af9; }}
    .css {{ color: #80cbc4; }}
    .attrs {{ color: var(--muted); font-size: 0.75rem; margin-top: 0.25rem; }}
    .url-cell {{ max-width: 200px; word-break: break-all; }}
    .element-block {{ min-width: 220px; }}
    pre {{
      background: #0b0d12;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.75rem;
      overflow-x: auto;
      font-size: 0.8rem;
    }}
    .muted {{ color: var(--muted); }}
    details summary {{ cursor: pointer; color: var(--accent); }}
    .replay-script {{
      font-size: 0.85rem;
      user-select: all;
      line-height: 1.6;
    }}
    .code-block {{
      background: #0b0d12;
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }}
    .code-block pre {{
      margin: 0;
      padding: 1rem 1.25rem;
      overflow-x: auto;
      font-size: 0.82rem;
      line-height: 1.55;
      user-select: all;
    }}
    .code-block code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #e8eaed;
    }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h1>Automation Run Report</h1>
      <p class="task">{_esc(data.get("task"))}</p>
    </div>
    <span class="badge {_status_class(status)}">{_esc(status)}</span>
  </div>

  <div class="summary-box">
    <strong>Summary</strong>
    <p>{_esc(data.get("summary") or "—")}</p>
  </div>

  {_render_stats(data)}

  <section>
    <h2>Metadata</h2>
    <table class="meta">
      {_render_metadata(data)}
    </table>
  </section>

  {_render_plan(data.get("plan") or {})}

  <section>
    <h2>Steps</h2>
    {_render_steps(data.get("steps") or [])}
  </section>

  {_render_replay_script(data)}

  <section>
    <h2>DOM / XPath Action Timeline</h2>
    <p class="muted">Every browser action from start to finish, with element locators and verification.</p>
    {_render_action_timeline(data.get("action_timeline") or [])}
  </section>
</body>
</html>
"""
