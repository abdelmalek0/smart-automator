from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..browser.history import DOMHistoryElement, enhanced_css_selector_for_history_element
from .context import ActionResult, AgentContext, PendingHitlHandoff
from .history import AgentStepRecord, BrowserStateHistory

log = logging.getLogger(__name__)

_HUMAN_CAPTURE_SCRIPT = """
(() => {
  if (window.__saHitlCaptureInstalled) return;
  window.__saHitlCaptureInstalled = true;

  const ATTRS = [
    'title', 'type', 'checked', 'name', 'role', 'value', 'placeholder',
    'data-date-format', 'data-state', 'alt', 'aria-checked', 'aria-label',
    'aria-expanded', 'href', 'id',
  ];

  function isInteractiveElement(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;
    const tag = element.tagName.toLowerCase();
    if (['button', 'a', 'input', 'textarea', 'select', 'label'].includes(tag)) return true;
    const role = element.getAttribute('role');
    if (role && ['button', 'link', 'menuitem', 'tab', 'checkbox', 'radio', 'textbox', 'combobox'].includes(role)) {
      return true;
    }
    if (element.hasAttribute('flt-tappable')) return true;
    if (element.getAttribute('tabindex') === '0') return true;
    if (element.getAttribute('aria-label')) return true;
    return false;
  }

  function resolveInteractiveTarget(element) {
    let current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE) {
      if (isInteractiveElement(current)) return current;
      current = current.parentElement;
    }
    return element;
  }

  function getXPath(element) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return '';
    const segments = [];
    let current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE) {
      let index = 1;
      let sibling = current.previousElementSibling;
      while (sibling) {
        if (sibling.tagName === current.tagName) index += 1;
        sibling = sibling.previousElementSibling;
      }
      const tag = current.tagName.toLowerCase();
      segments.unshift(index > 1 ? `${tag}[${index}]` : tag);
      current = current.parentElement;
    }
    return segments.join('/');
  }

  function collectAttributes(element) {
    const attrs = {};
    for (const name of ATTRS) {
      const value = element.getAttribute(name);
      if (value != null && value !== '') attrs[name] = value;
    }
    return attrs;
  }

  function visibleText(element) {
    const text = (element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim();
    return text ? text.slice(0, 120) : '';
  }

  function elementPayload(element, extra = {}) {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return null;
    return {
      tagName: element.tagName.toLowerCase(),
      xpath: getXPath(element),
      attributes: collectAttributes(element),
      value: element.value ?? '',
      inputType: element.type ?? '',
      label: visibleText(element),
      ...extra,
    };
  }

  function report(type, element, extra = {}) {
    const payload = elementPayload(element, { eventType: type, ...extra });
    if (!payload) return;
    try {
      window._saHumanAction(payload);
    } catch (err) {
      console.debug('HITL capture failed', err);
    }
  }

  const pendingInputs = new Map();

  function flushInput(xpath) {
    const entry = pendingInputs.get(xpath);
    if (!entry) return;
    pendingInputs.delete(xpath);
    report('input', entry.element, { text: entry.value });
  }

  document.addEventListener('click', (event) => {
    const target = event.target;
    if (!target || target.closest('#playwright-highlight-container')) return;
    const element = resolveInteractiveTarget(target);
    report('click', element);
  }, true);

  document.addEventListener('input', (event) => {
    const target = event.target;
    if (!target || !(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
    const xpath = getXPath(target);
    pendingInputs.set(xpath, { element: target, value: target.value });
  }, true);

  document.addEventListener('change', (event) => {
    const target = event.target;
    if (!target) return;
    if (target instanceof HTMLSelectElement) {
      const option = target.selectedOptions[0];
      report('select', target, { text: option ? option.text : target.value });
      return;
    }
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
      flushInput(getXPath(target));
    }
  }, true);

  document.addEventListener('keydown', (event) => {
    if (!['Enter', 'Tab', 'Escape'].includes(event.key)) return;
    const target = event.target;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
      flushInput(getXPath(target));
    }
    report('keydown', target, { keys: event.key });
  }, true);

  document.addEventListener('blur', (event) => {
    const target = event.target;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
      flushInput(getXPath(target));
    }
  }, true);

  window.__saFlushPendingInputs = () => {
    for (const xpath of Array.from(pendingInputs.keys())) {
      flushInput(xpath);
    }
  };
})();
"""

_FLUSH_PENDING_INPUTS_SCRIPT = (
    "(() => { if (window.__saFlushPendingInputs) window.__saFlushPendingInputs(); })();"
)


@dataclass
class _HitlCommand:
    action: str
    kwargs: dict[str, Any]
    done: threading.Event = field(default_factory=threading.Event)
    ok: bool = False
    error: str | None = None
    cancelled: bool = False


class HumanActionRecorder:
    """Records human browser interactions via injected capture script."""

    def __init__(
        self,
        context: AgentContext,
        on_action: Callable[[ActionResult, str, dict[str, Any]], None] | None = None,
    ):
        self._context = context
        self._on_action = on_action
        self._active = False
        self._binding_registered_contexts: set[int] = set()
        self._init_script_registered_contexts: set[int] = set()
        self._nav_handlers: dict[int, Callable] = {}
        self._active_page_id: int | None = None
        self._lock = threading.Lock()
        self._recorded: list[tuple[str, dict[str, Any], ActionResult]] = []
        self._last_url = ""

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def recorded(self) -> list[tuple[str, dict[str, Any], ActionResult]]:
        return list(self._recorded)

    def _iter_all_pages(self):
        browser_context = self._context.browser_context
        for page_id in browser_context.get_all_tab_ids():
            try:
                yield browser_context.get_page(page_id)
            except Exception:
                continue

    def _ensure_context_setup(self, playwright_page) -> None:
        pw_context = playwright_page.context
        context_key = id(pw_context)

        if context_key not in self._binding_registered_contexts:
            def _binding_handler(_source: Any, payload: dict[str, Any]) -> None:
                self._handle_capture_event(payload)

            pw_context.expose_binding("_saHumanAction", _binding_handler)
            self._binding_registered_contexts.add(context_key)

        if context_key not in self._init_script_registered_contexts:
            pw_context.add_init_script(_HUMAN_CAPTURE_SCRIPT)
            self._init_script_registered_contexts.add(context_key)

    def _inject_capture_script(self, playwright_page) -> None:
        self._ensure_context_setup(playwright_page)
        playwright_page.evaluate(_HUMAN_CAPTURE_SCRIPT)

    def _inject_all_open_pages(self) -> None:
        for page in self._iter_all_pages():
            try:
                self._inject_capture_script(page.playwright_page)
            except Exception:
                log.debug("HITL capture inject failed for page %s", page.page_id, exc_info=True)

    def _detach_nav_handler(self, page_id: int | None = None) -> None:
        if page_id is None:
            for tracked_page_id in list(self._nav_handlers):
                self._detach_nav_handler(tracked_page_id)
            return

        handler = self._nav_handlers.pop(page_id, None)
        if handler is None:
            return
        try:
            page = self._context.browser_context.get_page(page_id)
            page.playwright_page.remove_listener("framenavigated", handler)
        except Exception:
            log.debug("Failed to remove HITL navigation listener for page %s", page_id, exc_info=True)

    def _ensure_page_recording(self, page) -> None:
        playwright_page = page.playwright_page
        page_id = page.page_id

        self._ensure_context_setup(playwright_page)
        self._inject_capture_script(playwright_page)

        if page_id not in self._nav_handlers:
            def _on_navigate(frame) -> None:
                if frame != playwright_page.main_frame:
                    return
                url = frame.url
                try:
                    self._inject_capture_script(playwright_page)
                except Exception:
                    log.debug("HITL capture re-inject after navigation failed", exc_info=True)
                if not url or url == self._last_url:
                    return
                self._last_url = url
                self._record_navigation(url)

            playwright_page.on("framenavigated", _on_navigate)
            self._nav_handlers[page_id] = _on_navigate

        self._active_page_id = page_id

    def ensure_current_page(self) -> None:
        """Re-attach capture to the active tab if the human switched pages."""
        if not self._active:
            return
        try:
            page = self._context.browser_context.get_current_page()
        except Exception:
            return
        self._ensure_page_recording(page)

    def flush_pending_inputs(self) -> None:
        if not self._active:
            return
        for page in self._iter_all_pages():
            try:
                page.playwright_page.evaluate(_FLUSH_PENDING_INPUTS_SCRIPT)
            except Exception:
                log.debug(
                    "HITL pending-input flush failed for page %s",
                    page.page_id,
                    exc_info=True,
                )

    def clear_recorded(self) -> None:
        with self._lock:
            self._recorded.clear()

    def start(self) -> None:
        page = self._context.browser_context.get_current_page()
        self._last_url = page.url()

        if self._active:
            self.ensure_current_page()
            return

        self._recorded.clear()
        self._ensure_page_recording(page)
        self._inject_all_open_pages()
        self._active = True

    def stop(self, *, finalize: bool = True) -> list[tuple[str, dict[str, Any], ActionResult]]:
        if not self._active:
            return list(self._recorded)

        self._detach_nav_handler()
        self._active = False
        recorded = list(self._recorded)
        if finalize:
            self._recorded.clear()
            self._active_page_id = None
        return recorded

    def _record_navigation(self, url: str) -> None:
        action_name = "go_to_url"
        args = {"url": url}
        result = ActionResult(
            success=True,
            extracted_content=f"Human navigated to {url}",
            include_in_memory=True,
            action_name=action_name,
        )
        self._append_record(action_name, args, result)

    def _handle_capture_event(self, payload: dict[str, Any]) -> None:
        if not self._active:
            return
        with self._lock:
            event_type = payload.get("eventType", "")
            if event_type == "click":
                self._record_click(payload)
            elif event_type == "input":
                self._record_input(payload)
            elif event_type == "select":
                self._record_select(payload)
            elif event_type == "keydown":
                self._record_keys(payload)

    def _element_label(self, payload: dict[str, Any]) -> str:
        label = str(payload.get("label", "") or "").strip()
        if label:
            return label[:120]
        attrs = dict(payload.get("attributes") or {})
        for key in ("aria-label", "title", "placeholder", "name", "alt"):
            value = str(attrs.get(key, "") or "").strip()
            if value:
                return value[:120]
        return ""

    def _element_from_payload(self, payload: dict[str, Any]) -> DOMHistoryElement:
        element = DOMHistoryElement(
            tag_name=payload.get("tagName", ""),
            xpath=payload.get("xpath", ""),
            highlight_index=None,
            attributes=dict(payload.get("attributes") or {}),
        )
        css_selector = enhanced_css_selector_for_history_element(element)
        if css_selector:
            element.css_selector = css_selector
        return element

    def _dom_action_args(self, element: DOMHistoryElement, **extra: Any) -> dict[str, Any]:
        args: dict[str, Any] = {"xpath": element.xpath, **extra}
        if element.css_selector:
            args["css_selector"] = element.css_selector
        return args

    def _append_record(
        self,
        action_name: str,
        args: dict[str, Any],
        result: ActionResult,
        element: DOMHistoryElement | None = None,
    ) -> None:
        if element is not None:
            result.interacted_element = element
        result.action_name = action_name
        result.action_index = len(self._recorded) + 1
        self._recorded.append((action_name, args, result))
        if self._on_action:
            try:
                self._on_action(result, action_name, args)
            except Exception:
                log.debug("HITL on_action callback failed", exc_info=True)

    def _record_click(self, payload: dict[str, Any]) -> None:
        element = self._element_from_payload(payload)
        label = self._element_label(payload)
        args = self._dom_action_args(element, **({"label": label} if label else {}))
        if label:
            extracted_content = f"Human clicked {label!r}"
        else:
            extracted_content = f"Human clicked {element.tag_name}"
        result = ActionResult(
            success=True,
            extracted_content=extracted_content,
            include_in_memory=True,
            action_name="click_element",
            interacted_element=element,
        )
        self._append_record("click_element", args, result, element)

    def _record_input(self, payload: dict[str, Any]) -> None:
        element = self._element_from_payload(payload)
        text = str(payload.get("text", ""))
        label = self._element_label(payload)
        extra: dict[str, Any] = {"text": text}
        if label:
            extra["label"] = label
        args = self._dom_action_args(element, **extra)
        if label:
            extracted_content = f"Human entered text in {label!r}"
        else:
            extracted_content = f"Human entered text in {element.tag_name}"
        result = ActionResult(
            success=True,
            extracted_content=extracted_content,
            include_in_memory=True,
            action_name="input_text",
            interacted_element=element,
        )
        self._append_record("input_text", args, result, element)

    def _record_select(self, payload: dict[str, Any]) -> None:
        element = self._element_from_payload(payload)
        text = str(payload.get("text", ""))
        label = self._element_label(payload)
        extra: dict[str, Any] = {"text": text}
        if label:
            extra["label"] = label
        args = self._dom_action_args(element, **extra)
        if text:
            extracted_content = f"Human selected {text!r}"
        elif label:
            extracted_content = f"Human selected option on {label!r}"
        else:
            extracted_content = f"Human selected option on {element.tag_name}"
        result = ActionResult(
            success=True,
            extracted_content=extracted_content,
            include_in_memory=True,
            action_name="select_dropdown_option",
            interacted_element=element,
        )
        self._append_record("select_dropdown_option", args, result, element)

    def _record_keys(self, payload: dict[str, Any]) -> None:
        keys = str(payload.get("keys", ""))
        if not keys:
            return
        args = {"keys": keys}
        result = ActionResult(
            success=True,
            extracted_content=f"Human sent keys: {keys}",
            include_in_memory=True,
            action_name="send_keys",
        )
        self._append_record("send_keys", args, result)


class HitlController:
    """Coordinates human-in-the-loop pause, recording, and resume."""

    def __init__(
        self,
        context: AgentContext,
        *,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ):
        self._context = context
        self._emit = emit or (lambda _event: None)
        self._recorder = HumanActionRecorder(context, on_action=self._on_human_action)
        self._command_queue: queue.Queue[_HitlCommand] = queue.Queue()
        self._intervention_cycle = 0
        self._session_start_url = ""
        self._session_start_title = ""

    def submit_command(
        self,
        action: str,
        *,
        timeout: float = 60.0,
        wait: bool = True,
        **kwargs: Any,
    ) -> tuple[bool, str | None]:
        """Queue a HITL command for execution on the browser/executor thread."""
        if action == "take_control":
            self._context.hitl_interrupt = True
            self._emit({"type": "take_control_pending"})
        command = _HitlCommand(action=action, kwargs=kwargs)
        self._command_queue.put(command)
        if not wait:
            return True, None
        if not command.done.wait(timeout):
            command.cancelled = True
            if action == "take_control":
                self._context.hitl_interrupt = False
            return False, f"HITL command '{action}' timed out"
        return command.ok, command.error

    def process_pending_commands(self) -> None:
        while True:
            try:
                command = self._command_queue.get_nowait()
            except queue.Empty:
                break
            if command.cancelled:
                command.done.set()
                continue
            try:
                if command.action == "take_control":
                    command.ok = self.take_control(**command.kwargs)
                    if not command.ok:
                        command.error = "Failed to take control"
                elif command.action == "return_control":
                    command.ok = self.return_control()
                    if not command.ok:
                        command.error = "Failed to return control"
                else:
                    command.error = f"Unknown HITL command: {command.action}"
            except Exception as exc:
                command.ok = False
                command.error = str(exc)
                log.exception("HITL command %s failed", command.action)
            finally:
                if command.action == "take_control":
                    self._context.hitl_interrupt = False
                command.done.set()

        if self._context.human_controlling:
            try:
                self._recorder.ensure_current_page()
            except Exception:
                log.debug("HITL ensure_current_page failed", exc_info=True)

    @property
    def recorder(self) -> HumanActionRecorder:
        return self._recorder

    def set_enabled(self, enabled: bool) -> None:
        self._context.hitl_enabled = enabled

    def request_intervention(self, reason: str, *, source: str = "auto") -> bool:
        context = self._context
        if not context.hitl_enabled:
            return False
        if context.awaiting_human:
            context.hitl_reason = reason or context.hitl_reason
            context.hitl_source = source or context.hitl_source
            context.hitl_deadline = time.time() + context.options.hitl_timeout_seconds
            return True

        context.pause()
        context.awaiting_human = True
        context.hitl_reason = reason
        context.hitl_source = source
        context.hitl_deadline = time.time() + context.options.hitl_timeout_seconds
        self._intervention_cycle += 1

        self._emit(
            {
                "type": "human_intervention_required",
                "reason": reason,
                "deadline": context.hitl_deadline,
                "source": source,
                "cycle": self._intervention_cycle,
            }
        )
        self._emit({"type": "status", "status": "awaiting_human"})
        return True

    def take_control(self, *, source: str = "manual") -> bool:
        context = self._context
        if not context.hitl_enabled:
            return False
        if context.human_controlling:
            if not self._recorder.is_active:
                self._recorder.start()
            return True
        if not context.awaiting_human:
            self.request_intervention("Manual take control", source=source)
        try:
            page = context.browser_context.get_current_page()
            self._session_start_url = page.url()
            self._session_start_title = page.title()
        except Exception:
            self._session_start_url = ""
            self._session_start_title = ""
        context.human_controlling = True
        context.hitl_interrupt = False
        self._recorder.start()
        self._emit({"type": "human_control_started", "source": source})
        return True

    def return_control(self) -> bool:
        context = self._context
        if not context.human_controlling and not context.awaiting_human:
            return True

        self._capture_and_flush_recorded(set_handoff=True)

        context.message_manager.prepare_post_hitl_resume()
        context.action_results.clear()
        context.human_controlling = False
        context.awaiting_human = False
        context.hitl_reason = ""
        context.hitl_deadline = None
        context.force_replan_after_hitl = True
        context.post_hitl_fresh_start = True
        context.hitl_interrupt = False
        context.stuck_episode_active = False
        context.stuck_recovery_attempts = 0
        context.critic_runs_this_episode = 0
        context.consecutive_unvalidated_done = 0
        context.consecutive_no_action_steps = 0
        context.resume()

        self._emit({"type": "human_intervention_ended", "cycle": self._intervention_cycle})
        self._emit({"type": "status", "status": "running"})
        return True

    def check_timeout(self) -> bool:
        context = self._context
        if not context.awaiting_human:
            return False
        if context.hitl_deadline is None:
            return False
        if time.time() <= context.hitl_deadline:
            return False
        self._fail_timeout()
        return True

    def _fail_timeout(self) -> None:
        context = self._context
        if context.human_controlling:
            self.flush_recorded_to_history()
        context.human_controlling = False
        context.awaiting_human = False
        context.hitl_timed_out = True
        context.hitl_reason = "Human intervention timed out"
        context.stop()
        self._emit(
            {
                "type": "done",
                "status": "fail",
                "summary": "Human intervention timed out",
            }
        )

    def flush_recorded_to_history(self) -> bool:
        """Flush any buffered human actions into history (e.g. on cancel)."""
        context = self._context
        if not context.human_controlling and not self._recorder.is_active and not self._recorder.recorded:
            return False
        return bool(self._capture_and_flush_recorded(set_handoff=False))

    def _capture_and_flush_recorded(self, *, set_handoff: bool) -> list[tuple[str, dict[str, Any], ActionResult]]:
        context = self._context
        if self._recorder.is_active:
            self._recorder.flush_pending_inputs()
            recorded = self._recorder.stop(finalize=False)
        else:
            recorded = list(self._recorder.recorded)

        try:
            page = context.browser_context.get_current_page()
            end_url = page.url()
            end_title = page.title()
        except Exception:
            end_url = ""
            end_title = ""

        if set_handoff:
            context.pending_hitl_handoff = PendingHitlHandoff(
                recorded=recorded,
                intervention_reason=context.hitl_reason,
                intervention_source=context.hitl_source,
                cycle=self._intervention_cycle,
                start_url=self._session_start_url,
                start_title=self._session_start_title,
                end_url=end_url,
                end_title=end_title,
            )

        if not recorded:
            return []

        try:
            self._flush_to_history(recorded)
            self._recorder.clear_recorded()
            return recorded
        except Exception:
            log.exception("Failed to flush human actions to history")
            with self._recorder._lock:
                self._recorder._recorded[:] = recorded
            return recorded

    def _on_human_action(
        self,
        result: ActionResult,
        action_name: str,
        args: dict[str, Any],
    ) -> None:
        step_index = self._context.alloc_ui_step_index()
        self._emit(
            {
                "type": "human_action",
                "index": step_index,
                "action": action_name,
                "args": args,
                "result": result.extracted_content or "",
                "cycle": self._intervention_cycle,
            }
        )

    def _flush_to_history(
        self,
        recorded: list[tuple[str, dict[str, Any], ActionResult]],
    ) -> None:
        context = self._context
        page = context.browser_context.get_current_page()
        url = page.url()
        title = page.title()
        tabs = context.browser_context.get_tab_infos()

        for action_name, args, result in recorded:
            element = result.interacted_element
            interacted = [element] if element is not None else []
            model_output = json.dumps(
                {
                    "current_state": {
                        "evaluation_previous_goal": "Human",
                        "memory": "Human intervention",
                        "next_goal": action_name,
                    },
                    "action": [{action_name: args}],
                },
                ensure_ascii=False,
            )
            record = AgentStepRecord(
                model_output=model_output,
                result=[result],
                state=BrowserStateHistory(
                    url=url,
                    title=title,
                    tabs=tabs,
                    interacted_elements=interacted,
                ),
                metadata={"source": "human", "cycle": self._intervention_cycle},
            )
            context.history.history.append(record)

    @staticmethod
    def _redact_action_args(args: dict[str, Any]) -> dict[str, Any]:
        redacted = dict(args)
        if "text" in redacted:
            redacted["text"] = "[redacted]"
        return redacted

    @classmethod
    def _format_human_action_line(
        cls,
        action_name: str,
        args: dict[str, Any],
        result: ActionResult,
        *,
        redact_sensitive: bool = False,
    ) -> str:
        display_args = cls._redact_action_args(args) if redact_sensitive else args
        summary = result.extracted_content or action_name
        details: list[str] = []
        if display_args.get("label"):
            details.append(f"label={display_args['label']!r}")
        if display_args.get("text"):
            details.append(f"text={display_args['text']!r}")
        if display_args.get("url"):
            details.append(f"url={display_args['url']!r}")
        if display_args.get("keys"):
            details.append(f"keys={display_args['keys']!r}")
        attrs = dict(display_args.get("attributes") or {})
        for key in ("aria-label", "title"):
            value = attrs.get(key)
            if value:
                details.append(f"{key}={value!r}")
        if display_args.get("xpath"):
            details.append(f"xpath={display_args['xpath']!r}")
        if details:
            return f"{summary} ({', '.join(details)})"
        return summary

    @classmethod
    def _format_action_trace_lines(
        cls,
        recorded: list[tuple[str, dict[str, Any], ActionResult]],
        *,
        redact_sensitive: bool = False,
    ) -> list[str]:
        return [
            f"- {cls._format_human_action_line(action_name, args, result, redact_sensitive=redact_sensitive)}"
            for action_name, args, result in recorded
        ]

    @staticmethod
    def _should_include_remaining_work(analysis: dict[str, Any] | None) -> bool:
        if not analysis:
            return False
        confidence = str(analysis.get("confidence", "") or "").strip().lower()
        outcome = str(analysis.get("outcome", "") or "").strip().lower()
        if confidence in {"", "low"} or outcome in {"", "unclear"}:
            return False
        return bool(str(analysis.get("remaining_work", "") or "").strip())

    @classmethod
    def format_human_memory_message(
        cls,
        recorded: list[tuple[str, dict[str, Any], ActionResult]],
        *,
        intervention_reason: str = "",
        intervention_source: str = "",
        analysis: dict[str, Any] | None = None,
    ) -> str:
        lines = [
            "Human intervention handoff. Treat the current page state as authoritative "
            "and avoid repeating completed human steps unless the page changed."
        ]
        if intervention_source:
            lines.append(f"Intervention source: {intervention_source}")
        if intervention_reason:
            lines.append(f"Trigger context: {intervention_reason}")
        if analysis:
            for key, label in (
                ("inferred_reason", "Inferred reason"),
                ("goal_achieved", "Goal achieved"),
                ("outcome", "Outcome"),
                ("evidence", "Evidence"),
                ("confidence", "Confidence"),
            ):
                value = str(analysis.get(key, "") or "").strip()
                if value:
                    lines.append(f"{label}: {value}")
            if cls._should_include_remaining_work(analysis):
                remaining_work = str(analysis.get("remaining_work", "") or "").strip()
                if remaining_work:
                    lines.append(f"Remaining work: {remaining_work}")
            elif str(analysis.get("confidence", "") or "").strip().lower() in {"", "low"} or str(
                analysis.get("outcome", "") or ""
            ).strip().lower() in {"", "unclear"}:
                lines.append(
                    "Guidance: Continue from the current page; do not undo human navigation."
                )
        if recorded:
            lines.append("Human action trace:")
            lines.extend(
                cls._format_action_trace_lines(recorded, redact_sensitive=bool(analysis))
            )
        return "\n".join(lines)

    def inject_human_memory(
        self,
        recorded: list[tuple[str, dict[str, Any], ActionResult]],
        *,
        intervention_reason: str = "",
        intervention_source: str = "",
        analysis: dict[str, Any] | None = None,
    ) -> None:
        message = self.format_human_memory_message(
            recorded,
            intervention_reason=intervention_reason,
            intervention_source=intervention_source,
            analysis=analysis,
        )
        self._context.message_manager.add_message_with_tokens(
            {"role": "user", "content": message},
            "hitl_handoff",
        )
