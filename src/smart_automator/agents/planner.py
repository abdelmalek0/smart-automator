from __future__ import annotations

from typing import TYPE_CHECKING

from ..actions.builder import NavigatorActionRegistry, parse_actions
from ..actions.schemas import Action
from ..agent.context import ActionResult, AgentContext
from ..agent.messages.utils import filter_external_content
from ..utils.prompts import get_planner_system_prompt
from .base import BaseAgent
from .output_schemas import validate_planner_output
from ..llm.base import BaseLLM

if TYPE_CHECKING:
    from ..agent.messages.service import MessageManager


class PlannerAgent(BaseAgent):
    def __init__(self, llm: BaseLLM, context: AgentContext, message_manager: MessageManager):
        super().__init__(
            llm,
            get_planner_system_prompt(),
            message_manager=message_manager,
            agent_id="planner",
        )
        self._context = context

    def execute(self) -> dict:
        messages = self._get_messages()
        planner_messages = [{"role": "system", "content": self._system_prompt}, *messages[1:]]
        try:
            response = self.get_json_response(planner_messages, temperature=0.5)
            response = validate_planner_output(response)
        except Exception as error:
            return {
                "id": self.id,
                "result": {
                    "observation": "",
                    "done": False,
                    "challenges": f"Planner failed to parse model output: {error}",
                    "next_steps": "Continue the task from the current page state.",
                    "final_answer": "",
                    "reasoning": "",
                    "web_task": True,
                },
            }

        result = {
            "observation": filter_external_content(response.get("observation", "")),
            "done": response.get("done", False),
            "challenges": filter_external_content(self._to_str(response.get("challenges", ""))),
            "next_steps": filter_external_content(self._to_str(response.get("next_steps", ""))),
            "final_answer": filter_external_content(response.get("final_answer", "")),
            "reasoning": filter_external_content(response.get("reasoning", "")),
            "web_task": response.get("web_task", True),
        }
        return {"id": self.id, "result": result}

    @staticmethod
    def _to_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() == "true"
        return bool(value)

    @staticmethod
    def _to_str(value) -> str:
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return str(value) if value is not None else ""
