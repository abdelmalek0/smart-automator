from pathlib import Path

from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os

DEFAULT_CHROME_PROFILE_DIR = Path.home() / ".local" / "share" / "smart-automator-chrome"

DEFAULT_INCLUDE_ATTRIBUTES = [
    "title", "type", "checked", "name", "role", "value", "placeholder",
    "data-date-format", "data-state", "alt", "aria-checked", "aria-label",
    "aria-expanded", "href",
]


class Config(BaseModel):
    llm_provider: str = "groq"
    planner_llm_provider: str = ""
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_api_key: str = ""
    google_api_key: str = ""
    google_model: str = "gemini-2.5-flash"
    openai_base_url: str = ""
    active_provider: str = ""
    active_model: str = ""
    headless: bool = False
    home_page_url: str = "https://www.google.com"
    viewport_width: int = 1280
    viewport_height: int = 1100
    viewport_expansion: int = 0
    max_steps: int = 100
    planning_interval: int = 3
    max_actions_per_step: int = 5
    max_failures: int = 5
    max_input_tokens: int = 64000
    max_observation_elements: int = 80
    max_observation_chars: int = 12000
    include_attributes: list[str] = Field(default_factory=lambda: list(DEFAULT_INCLUDE_ATTRIBUTES))
    include_dynamic_attributes: bool = True
    minimum_wait_page_load_time: float = 0.25
    wait_for_network_idle_page_load_time: float = 0.5
    maximum_wait_page_load_time: float = 5.0
    action_delay_seconds: float = 0.5
    replay_action_retry_wait_seconds: float = 15.0
    replay_show_highlights: bool = False
    allowed_urls: list[str] = Field(default_factory=list)
    denied_urls: list[str] = Field(default_factory=list)
    cdp_url: str = ""
    fresh_profile: bool = False
    chrome_user_data: str = ""


def default_chrome_user_data() -> str:
    return str(DEFAULT_CHROME_PROFILE_DIR)


def resolve_chrome_user_data(explicit: str, *, fresh_profile: bool) -> str:
    if fresh_profile:
        return ""
    stripped = (explicit or "").strip()
    if stripped:
        return stripped
    return default_chrome_user_data()


def browser_session_mode(
    *,
    cdp_url: str = "",
    fresh_profile: bool = False,
) -> str:
    if (cdp_url or "").strip():
        return "cdp"
    if fresh_profile:
        return "ephemeral"
    return "persistent"


def _parse_list(value: str) -> list[str]:
    if not value.strip():
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def load_config() -> Config:
    load_dotenv()
    return Config(
        llm_provider=os.getenv("LLM_PROVIDER", "groq"),
        planner_llm_provider=os.getenv("PLANNER_LLM_PROVIDER", ""),
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
        ollama_api_key=os.getenv("OLLAMA_API_KEY", ""),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_model=os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"),
        headless=os.getenv("HEADLESS", "false").lower() == "true",
        home_page_url=os.getenv("HOME_PAGE_URL", "https://www.google.com"),
        viewport_width=int(os.getenv("VIEWPORT_WIDTH", "1280")),
        viewport_height=int(os.getenv("VIEWPORT_HEIGHT", "1100")),
        viewport_expansion=int(os.getenv("VIEWPORT_EXPANSION", "0")),
        max_steps=int(os.getenv("MAX_STEPS", "100")),
        planning_interval=int(os.getenv("PLANNING_INTERVAL", "3")),
        max_actions_per_step=int(os.getenv("MAX_ACTIONS_PER_STEP", "5")),
        max_failures=int(os.getenv("MAX_FAILURES", "5")),
        max_input_tokens=int(os.getenv("MAX_INPUT_TOKENS", "64000")),
        max_observation_elements=int(os.getenv("MAX_OBSERVATION_ELEMENTS", "80")),
        max_observation_chars=int(os.getenv("MAX_OBSERVATION_CHARS", "12000")),
        include_attributes=_parse_list(os.getenv("INCLUDE_ATTRIBUTES", ",".join(DEFAULT_INCLUDE_ATTRIBUTES)))
        or list(DEFAULT_INCLUDE_ATTRIBUTES),
        include_dynamic_attributes=os.getenv("INCLUDE_DYNAMIC_ATTRIBUTES", "true").lower() == "true",
        minimum_wait_page_load_time=float(os.getenv("MINIMUM_WAIT_PAGE_LOAD_TIME", "0.25")),
        wait_for_network_idle_page_load_time=float(os.getenv("WAIT_FOR_NETWORK_IDLE_PAGE_LOAD_TIME", "0.5")),
        maximum_wait_page_load_time=float(os.getenv("MAXIMUM_WAIT_PAGE_LOAD_TIME", "5.0")),
        action_delay_seconds=float(os.getenv("ACTION_DELAY_SECONDS", "0.5")),
        replay_action_retry_wait_seconds=float(
            os.getenv("REPLAY_ACTION_RETRY_WAIT_SECONDS", "15.0")
        ),
        replay_show_highlights=os.getenv("REPLAY_SHOW_HIGHLIGHTS", "false").lower() == "true",
        allowed_urls=_parse_list(os.getenv("ALLOWED_URLS", "")),
        denied_urls=_parse_list(os.getenv("DENIED_URLS", "")),
        cdp_url=os.getenv("CDP_URL", ""),
        fresh_profile=os.getenv("QA_FRESH_PROFILE", "false").lower() == "true",
        chrome_user_data=os.getenv("CHROME_USER_DATA", ""),
    )
