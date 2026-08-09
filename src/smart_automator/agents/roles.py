"""Agent role registry for LLM configuration."""

from __future__ import annotations

from typing import Literal

AgentRole = Literal["navigation", "planning"]

AGENT_ROLES: tuple[AgentRole, ...] = ("navigation", "planning")

AGENT_ID_TO_ROLE: dict[str, AgentRole] = {
    "navigator": "navigation",
    "criteria_checker": "navigation",
    "planner": "planning",
    "action_critic": "planning",
    "hitl_debrief": "planning",
}

ROLE_LABELS: dict[AgentRole, str] = {
    "navigation": "Navigation",
    "planning": "Planning",
}

ROLE_DESCRIPTIONS: dict[AgentRole, str] = {
    "navigation": "Navigator and criteria checker",
    "planning": "Planner, actor-critic, and HITL debrief",
}

ROLE_AGENT_NAMES: dict[AgentRole, str] = {
    "navigation": "Navigator, Criteria Checker",
    "planning": "Planner, Actor-Critic, HITL Debrief",
}


def is_agent_role(value: str) -> bool:
    return value in AGENT_ROLES


def role_for_agent_id(agent_id: str) -> AgentRole | None:
    return AGENT_ID_TO_ROLE.get(agent_id)
