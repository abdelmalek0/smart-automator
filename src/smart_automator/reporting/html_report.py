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


def _fmt_duration_ms(ms: float | int | None) -> str:
    if ms is None:
        return "—"
    ms = float(ms)
    if ms <= 0:
        return "0s"
    secs = ms / 1000
    if secs < 10:
        return f"{secs:.1f}s"
    if secs < 60:
        return f"{round(secs)}s"
    minutes = int(secs // 60)
    remainder = round(secs % 60)
    return f"{minutes}m {remainder}s"


def _truncate(text: str, max_len: int = 80) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _render_summary_strip(data: dict[str, Any]) -> str:
    status = data.get("status", "unknown")

    header_line = " · ".join(
        part
        for part in [
            f'<span class="badge {_status_class(status)}">{_esc(status)}</span>',
            f'<span class="mono">{_esc(data.get("run_id", "")[:8])}</span>',
        ]
        if part
    )

    context_lines: list[str] = []
    website_name = data.get("website_name")
    website_url = data.get("website_url")
    if website_name and website_url:
        context_lines.append(
            f'<p class="context-line">Website: <strong>{_esc(website_name)}</strong> '
            f'→ <a href="{_esc(website_url)}" target="_blank" rel="noopener">{_esc(website_url)}</a></p>'
        )
    elif website_url:
        context_lines.append(
            f'<p class="context-line">URL: <a href="{_esc(website_url)}" target="_blank" rel="noopener">{_esc(website_url)}</a></p>'
        )
    elif data.get("detected_urls"):
        urls = data["detected_urls"]
        links = ", ".join(
            f'<a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(url)}</a>'
            for url in urls[:3]
        )
        context_lines.append(f'<p class="context-line">Detected URLs: {links}</p>')

    context_prompt = data.get("context_prompt")
    if context_prompt:
        context_lines.append(f'<p class="context-prompt">{_esc(context_prompt)}</p>')

    task_only = data.get("task_only") or data.get("task") or ""
    context_lines.append(f'<p class="task">{_esc(task_only)}</p>')

    test_name = data.get("name")
    if test_name:
        context_lines.append(f'<p class="context-line">Test name: <strong>{_esc(test_name)}</strong></p>')

    success_criteria = data.get("success_criteria")
    if success_criteria:
        context_lines.append(
            f'<p class="context-line">Success criteria: {_esc(success_criteria)}</p>'
        )

    verdict = data.get("criteria_verdict") or {}
    if verdict:
        passed = verdict.get("passed")
        verdict_status = "pass" if passed else "fail"
        context_lines.append(
            f'<p class="context-line">Criteria verdict: '
            f'<span class="badge {_status_class(verdict_status)}">'
            f'{"passed" if passed else "failed"}</span></p>'
        )
        if verdict.get("reason"):
            context_lines.append(f'<p class="context-prompt">{_esc(verdict["reason"])}</p>')
        if verdict.get("evidence"):
            context_lines.append(f'<p class="context-prompt muted">Evidence: {_esc(verdict["evidence"])}</p>')

    return f"""
    <div class="summary-strip">
      <div class="header-line">{header_line}</div>
      {"".join(context_lines)}
    </div>
    """


def _render_stat_cards(data: dict[str, Any]) -> str:
    tokens = data.get("tokens") or {}
    input_tokens = int(tokens.get("input", tokens.get("prompt", 0)) or 0)
    output_tokens = int(tokens.get("output", tokens.get("completion", 0)) or 0)
    cache_tokens = int(tokens.get("cache", 0) or 0)
    total_tokens = int(tokens.get("total", 0) or 0)
    timing = data.get("turn_timing") or {}

    token_sub_parts = [f"{input_tokens:,} in / {output_tokens:,} out"]
    if cache_tokens > 0:
        token_sub_parts.append(f"cache {cache_tokens:,}")
    token_sub = f'<div class="stat-sub">{" · ".join(token_sub_parts)}</div>'

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
        <div class="stat-value">{total_tokens:,}</div>
        {token_sub if total_tokens > 0 else ""}
      </div>
      <div class="stat-card">
        <div class="stat-label">Est. cost</div>
        <div class="stat-value">{_esc(_fmt_cost(tokens.get("cost_usd")))}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Step time (sum)</div>
        <div class="stat-value">{_esc(_fmt_duration_ms(data.get("step_elapsed_ms")))}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Last turn timing</div>
        <div class="stat-value">{_esc(_fmt_duration_ms(timing.get("turn_ms")))}</div>
        <div class="stat-sub">DOM {_esc(_fmt_duration_ms(timing.get("snapshot_ms")))} · LLM {_esc(_fmt_duration_ms(timing.get("llm_navigator_ms")))} · Act {_esc(_fmt_duration_ms(timing.get("batch_ms")))} · Settle {_esc(_fmt_duration_ms(timing.get("settle_ms")))}</div>
      </div>
    </div>
    """


def _render_run_config(data: dict[str, Any]) -> str:
    llm = data.get("llm") or {}
    rows = [
        ("Run ID", data.get("run_id")),
        ("Test name", data.get("name") or "—"),
        ("Success criteria", data.get("success_criteria") or "—"),
        ("Source run", data.get("source_run_id") or "—"),
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
    table_rows = "\n".join(
        f"<tr><th>{_esc(label)}</th><td>{_esc(value)}</td></tr>"
        for label, value in rows
    )
    return f"""
    <details class="config-details">
      <summary>Run configuration</summary>
      <table class="meta">
        {table_rows}
      </table>
    </details>
    """


def _render_screenshot_thumb(step: dict[str, Any]) -> str:
    screenshot_src = step.get("screenshot_src")
    if not screenshot_src:
        return '<span class="muted">—</span>'
    if step.get("screenshot_missing"):
        return '<span class="muted" title="Screenshot file missing">missing</span>'
    index = step.get("index", "")
    return (
        f'<img class="step-thumb" src="{_esc(screenshot_src)}" '
        f'alt="Step {index} screenshot" loading="lazy" />'
    )


def _render_screenshot_full(step: dict[str, Any]) -> str:
    screenshot_src = step.get("screenshot_src")
    if not screenshot_src:
        return ""
    if step.get("screenshot_missing"):
        return '<p class="muted">Screenshot file not found on disk.</p>'
    index = step.get("index", "")
    return (
        f'<img class="step-screenshot" src="{_esc(screenshot_src)}" '
        f'alt="Step {index} screenshot" />'
    )


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


def _render_step_actions(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return ""
    rows: list[str] = []
    for entry in actions:
        status = entry.get("verification_status") or ("pass" if entry.get("executed") else "fail")
        if entry.get("error"):
            status = "error"
        outcome = (
            entry.get("verification_evidence")
            or entry.get("extracted_content")
            or entry.get("error")
            or ""
        )
        rows.append(
            f"""
            <tr>
              <td>{entry.get("action_num")}</td>
              <td><code>{_esc(entry.get("action"))}</code></td>
              <td class="mono">{_esc(json.dumps(entry.get("args") or {}, default=str))}</td>
              <td class="url-cell">{_esc(entry.get("url"))}</td>
              <td>{_render_element(entry.get("element"))}</td>
              <td><span class="badge {_status_class(status)}">{_esc(status)}</span></td>
              <td>{_esc(outcome)}</td>
            </tr>
            """
        )
    return f"""
    <div class="step-actions">
      <h4>Actions</h4>
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
    </div>
    """


def _render_steps(steps: list[dict[str, Any]], timeline_by_step: dict[int, list[dict[str, Any]]]) -> str:
    if not steps:
        return '<p class="muted">No steps recorded.</p>'

    rows: list[str] = []
    for step in steps:
        status = step.get("status", "")
        index = int(step.get("index") or 0)
        thought = str(step.get("thought") or "")
        args_json = json.dumps(step.get("args") or {}, indent=2, default=str)
        step_actions = timeline_by_step.get(index, [])
        details_id = f"step-details-{index}"

        rows.append(
            f"""
            <tr class="step-row">
              <td class="step-num">{index}</td>
              <td><span class="badge {_status_class(status)}">{_esc(status)}</span></td>
              <td class="mono"><code>{_esc(step.get("action"))}</code></td>
              <td class="thought-cell" title="{_esc(thought)}">{_esc(_truncate(thought))}</td>
              <td class="thumb-cell">{_render_screenshot_thumb(step)}</td>
              <td class="elapsed-cell">{_esc(_fmt_duration_ms(step.get("elapsed_ms")))}</td>
            </tr>
            <tr class="step-expand">
              <td colspan="6">
                <details class="step-details" id="{details_id}">
                  <summary>Details</summary>
                  <div class="step-detail-body">
                    <p class="step-thought"><strong>Thought:</strong> {_esc(thought)}</p>
                    <p><strong>Result:</strong> {_esc(step.get("result"))}</p>
                    <details>
                      <summary>Args</summary>
                      <pre>{_esc(args_json)}</pre>
                    </details>
                    {_render_step_actions(step_actions)}
                    {_render_screenshot_full(step)}
                  </div>
                </details>
              </td>
            </tr>
            """
        )

    return f"""
    <div class="table-wrap">
      <table class="step-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Status</th>
            <th>Action</th>
            <th>Thought</th>
            <th>Screenshot</th>
            <th>Time</th>
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
    if not completed and not remaining and not in_progress:
        return ""

    parts = ['<details class="plan-details"><summary>Plan</summary>']
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
    parts.append("</details>")
    return "\n".join(parts)


def _render_replay_script(data: dict[str, Any]) -> str:
    script = data.get("replay_script") or ""
    if not script.strip():
        return ""
    return f"""
    <details class="replay-details">
      <summary>Automatic Execution</summary>
      <p class="muted">Copy-paste Playwright Python script for LLM-free replay.</p>
      <div class="code-block">
        <pre><code class="language-python">{_esc(script)}</code></pre>
      </div>
    </details>
    """


def render_html_report(data: dict[str, Any]) -> str:
    timeline_by_step = data.get("timeline_by_step") or {}
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
      padding: 1.5rem;
    }}
    h1, h2, h3, h4 {{ margin-top: 0; }}
    h1 {{ font-size: 1.5rem; margin-bottom: 0.75rem; }}
    h2 {{ font-size: 1.1rem; margin: 1.25rem 0 0.75rem; border-bottom: 1px solid var(--border); padding-bottom: 0.35rem; }}
    h3 {{ font-size: 0.95rem; margin: 0.75rem 0 0.35rem; color: var(--muted); }}
    h4 {{ font-size: 0.85rem; margin: 0.75rem 0 0.35rem; color: var(--muted); }}
    a {{ color: var(--accent); }}
    .badge {{
      display: inline-block;
      padding: 0.1rem 0.45rem;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      background: var(--border);
      white-space: nowrap;
    }}
    .status-pass {{ background: rgba(52,168,83,0.2); color: var(--pass); }}
    .status-fail {{ background: rgba(234,67,53,0.2); color: var(--fail); }}
    .status-warn {{ background: rgba(251,188,4,0.15); color: var(--warn); }}
    .summary-box {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem 1rem;
      margin-bottom: 1rem;
    }}
    .summary-strip {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem 1rem;
      margin-bottom: 1rem;
    }}
    .header-line {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.85rem;
      margin-bottom: 0.35rem;
    }}
    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 0.65rem;
      margin-bottom: 1rem;
    }}
    .stat-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.7rem 0.85rem;
    }}
    .stat-label {{ color: var(--muted); font-size: 0.75rem; }}
    .stat-value {{ font-size: 1.2rem; font-weight: 700; margin-top: 0.1rem; }}
    .stat-sub {{ color: var(--muted); font-size: 0.72rem; margin-top: 0.2rem; }}
    .context-line {{ margin: 0.25rem 0; font-size: 0.85rem; }}
    .context-prompt {{
      margin: 0.25rem 0;
      font-size: 0.8rem;
      color: var(--muted);
      white-space: pre-wrap;
    }}
    .task {{ color: var(--accent); white-space: pre-wrap; margin: 0.35rem 0 0; font-size: 0.9rem; }}
    .config-details, .plan-details, .replay-details {{
      margin: 0.75rem 0;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.5rem 0.75rem;
    }}
    .config-details summary, .plan-details summary, .replay-details summary, .step-details summary {{
      cursor: pointer;
      color: var(--accent);
      font-size: 0.85rem;
      user-select: none;
    }}
    table.meta {{
      border-collapse: collapse;
      width: 100%;
      margin-top: 0.5rem;
      font-size: 0.8rem;
    }}
    table.meta th, table.meta td {{
      text-align: left;
      padding: 0.3rem 0.6rem 0.3rem 0;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }}
    table.meta th {{ color: var(--muted); width: 140px; font-weight: 500; }}
    .table-wrap {{ overflow-x: auto; }}
    .step-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }}
    .step-table th, .step-table td {{
      border: 1px solid var(--border);
      padding: 0.4rem 0.55rem;
      vertical-align: middle;
    }}
    .step-table th {{
      background: var(--surface);
      text-align: left;
      color: var(--muted);
      font-size: 0.75rem;
      font-weight: 600;
    }}
    .step-row td {{ background: var(--surface); }}
    .step-expand td {{
      padding: 0;
      border-top: none;
      background: #12151c;
    }}
    .step-num {{ width: 2rem; text-align: center; font-weight: 700; }}
    .thought-cell {{
      max-width: 280px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--muted);
      font-style: italic;
    }}
    .thumb-cell {{ width: 90px; text-align: center; }}
    .elapsed-cell {{ width: 70px; text-align: right; color: var(--muted); font-size: 0.75rem; white-space: nowrap; }}
    .step-thumb {{
      max-height: 48px;
      max-width: 80px;
      border-radius: 4px;
      border: 1px solid var(--border);
      vertical-align: middle;
    }}
    .step-details {{ padding: 0.5rem 0.75rem; }}
    .step-detail-body {{ padding: 0.5rem 0; }}
    .step-thought {{ color: var(--muted); font-style: italic; font-size: 0.85rem; }}
    .step-screenshot {{
      max-width: 100%;
      border-radius: 6px;
      border: 1px solid var(--border);
      margin-top: 0.5rem;
    }}
    .step-actions {{ margin-top: 0.75rem; }}
    .timeline-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.78rem;
    }}
    .timeline-table th, .timeline-table td {{
      border: 1px solid var(--border);
      padding: 0.35rem 0.5rem;
      vertical-align: top;
    }}
    .timeline-table th {{
      background: var(--surface);
      text-align: left;
      color: var(--muted);
    }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.78rem; word-break: break-all; }}
    .xpath {{ color: #c58af9; }}
    .css {{ color: #80cbc4; }}
    .attrs {{ color: var(--muted); font-size: 0.72rem; margin-top: 0.2rem; }}
    .url-cell {{ max-width: 180px; word-break: break-all; }}
    .element-block {{ min-width: 180px; }}
    pre {{
      background: #0b0d12;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.6rem;
      overflow-x: auto;
      font-size: 0.78rem;
    }}
    .muted {{ color: var(--muted); }}
    details summary {{ cursor: pointer; color: var(--accent); }}
    .code-block {{
      background: #0b0d12;
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      margin-top: 0.5rem;
    }}
    .code-block pre {{
      margin: 0;
      padding: 0.75rem 1rem;
      overflow-x: auto;
      font-size: 0.78rem;
      line-height: 1.5;
      user-select: all;
    }}
    .code-block code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #e8eaed;
    }}
  </style>
</head>
<body>
  <h1>Automation Run Report</h1>

  {_render_summary_strip(data)}

  {_render_stat_cards(data)}

  <div class="summary-box">
    <strong>Summary</strong>
    <p style="margin:0.35rem 0 0">{_esc(data.get("summary") or "—")}</p>
  </div>

  {_render_run_config(data)}

  {_render_plan(data.get("plan") or {})}

  <section>
    <h2>Steps</h2>
    {_render_steps(data.get("steps") or [], timeline_by_step)}
  </section>

  {_render_replay_script(data)}
</body>
</html>
"""
