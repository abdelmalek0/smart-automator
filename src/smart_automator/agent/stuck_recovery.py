from __future__ import annotations

from dataclasses import dataclass, field

from .context import ActionResult, AgentContext

STALE_PAGE_STEP_THRESHOLD = 5
MAX_CRITIC_RUNS_PER_EPISODE = 3


@dataclass
class StuckSignals:
    auto_wait_with_elements: bool = False
    submit_hint_fired: bool = False
    no_progress_on_same_page: bool = False
    action_errors: bool = False
    verification_issues: bool = False
    consecutive_no_action_steps: int = 0
    num_highlights: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def needs_planner_recovery(self) -> bool:
        if self.auto_wait_with_elements and self.consecutive_no_action_steps >= 2:
            return True
        if self.submit_hint_fired:
            return True
        if self.no_progress_on_same_page:
            return True
        if self.action_errors:
            return True
        if self.verification_issues:
            return True
        return False

    def needs_action_critic(self, critic_runs_this_episode: int) -> bool:
        if critic_runs_this_episode >= MAX_CRITIC_RUNS_PER_EPISODE:
            return False
        if self.submit_hint_fired:
            return True
        if self.auto_wait_with_elements and self.consecutive_no_action_steps >= 2:
            return True
        if self.no_progress_on_same_page and self.consecutive_no_action_steps >= 1:
            return True
        return False


def _had_meaningful_progress(
    *,
    url_changed: bool,
    title_changed: bool,
    action_errors: bool,
    auto_wait: bool,
    submit_hint_fired: bool,
    only_wait_actions: bool,
    only_done_action: bool,
) -> bool:
    if url_changed or title_changed:
        return True
    if action_errors or auto_wait or submit_hint_fired or only_done_action:
        return False
    return not only_wait_actions


def update_page_progress(
    context: AgentContext,
    *,
    url: str,
    title: str,
    action_errors: bool,
    auto_wait: bool,
    submit_hint_fired: bool,
    only_wait_actions: bool,
    only_done_action: bool = False,
) -> int:
    url_changed = context.last_page_url is not None and context.last_page_url != url
    title_changed = context.last_page_title is not None and context.last_page_title != title

    if _had_meaningful_progress(
        url_changed=url_changed,
        title_changed=title_changed,
        action_errors=action_errors,
        auto_wait=auto_wait,
        submit_hint_fired=submit_hint_fired,
        only_wait_actions=only_wait_actions,
        only_done_action=only_done_action,
    ):
        context.stale_steps_on_same_page = 0
        context.stuck_episode_active = False
        context.critic_runs_this_episode = 0
        context.consecutive_unvalidated_done = 0
        context.awaiting_done_recovery = False
    else:
        if context.last_page_url == url and context.last_page_title == title:
            context.stale_steps_on_same_page += 1
        else:
            context.stale_steps_on_same_page = 1

    context.last_page_url = url
    context.last_page_title = title
    return context.stale_steps_on_same_page


def detect_stuck_signals(
    context: AgentContext,
    *,
    auto_wait: bool,
    consecutive_no_action_steps: int,
    num_highlights: int,
    submit_hint_fired: bool,
    action_results: list[ActionResult],
    stale_steps_on_same_page: int,
    verification_issues: int = 0,
) -> StuckSignals:
    action_errors = any(result.error for result in action_results)
    verification_failed = any(result.verification_status == "failed" for result in action_results)
    verification_no_effect = sum(
        1 for result in action_results if result.verification_status == "no_effect"
    )
    signals = StuckSignals(
        auto_wait_with_elements=auto_wait and num_highlights > 0,
        submit_hint_fired=submit_hint_fired,
        no_progress_on_same_page=stale_steps_on_same_page >= STALE_PAGE_STEP_THRESHOLD,
        action_errors=action_errors,
        verification_issues=verification_failed or verification_no_effect >= 2 or verification_issues >= 2,
        consecutive_no_action_steps=consecutive_no_action_steps,
        num_highlights=num_highlights,
    )

    if signals.auto_wait_with_elements and consecutive_no_action_steps >= 2:
        signals.reasons.append(
            f"no parseable actions for {consecutive_no_action_steps} steps with "
            f"{num_highlights} visible element(s)"
        )
    if submit_hint_fired:
        signals.reasons.append("Enter/OK/Submit still visible after entry")
    if signals.no_progress_on_same_page:
        signals.reasons.append(
            f"same page for {stale_steps_on_same_page} step(s) without progress"
        )
    if action_errors:
        signals.reasons.append("action execution errors on the last step")
    if verification_failed:
        signals.reasons.append("action verification failed on the last step")
    elif verification_no_effect >= 2:
        signals.reasons.append("multiple actions had no observable effect")

    if signals.needs_planner_recovery:
        context.stuck_episode_active = True

    return signals


def should_block_navigator_done(context: AgentContext) -> bool:
    if context.stuck_episode_active:
        return True
    if context.stale_steps_on_same_page >= 2:
        return True
    if context.consecutive_unvalidated_done >= 1:
        return True
    return False


def build_premature_done_rejection_hint(plan_result: dict | None) -> str:
    lines = [
        "Navigator claimed the task was complete, but the planner has NOT confirmed completion.",
        "Perform the planner's concrete next steps on the CURRENT page — do not idle with wait.",
        "Do NOT call done again until the CURRENT page state visibly shows the task is finished.",
        "A second failed confirmation, or idle wait after done is blocked, ends the run with a criteria grade (pass or fail).",
        "Re-read the indexed interactive elements — do not rely on memory alone.",
        'Respond with flat JSON and a non-empty action array (click_element, input_text, wait, etc.).',
    ]
    if plan_result:
        challenges = plan_result.get("challenges", "")
        next_steps = plan_result.get("next_steps", "")
        if challenges:
            lines.append(f"Planner challenges: {challenges}")
        if next_steps:
            lines.append(f"Planner next steps: {next_steps}")
    return "\n".join(lines)


def build_stuck_recovery_hint(signals: StuckSignals, diagnostics: dict | None) -> str:
    lines = [
        "Navigator appears stuck. The planner will re-evaluate; the navigator must act next.",
        f"Signals: {'; '.join(signals.reasons) if signals.reasons else 'unknown'}.",
        'Respond with flat JSON only: {"current_state": {...}, "action": [{...}]}.',
        "Do not wrap output in AgentOutput or tool-call envelopes.",
        "For PIN keypads, click each digit by index, then click Enter/OK/Submit.",
        "For forms, fill required fields, then click the confirm/submit control.",
        "Use action verification notes in the history to decide whether to retry or continue.",
    ]
    if diagnostics and diagnostics.get("raw_preview"):
        lines.append(f"Last model output preview: {diagnostics['raw_preview']}")
    return "\n".join(lines)
