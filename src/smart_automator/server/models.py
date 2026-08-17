from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smart_automator.config import normalize_browser_overrides

RUN_MODE_TRAINING = "training"
RUN_MODE_MANUAL = "manual"
RUN_MODE_AUTOMATIC = "automatic"
VALID_RUN_MODES = frozenset({RUN_MODE_TRAINING, RUN_MODE_MANUAL, RUN_MODE_AUTOMATIC})
MANUAL_PLACEHOLDER_TASK = "Human demonstration"


def resolve_run_mode(run_mode: str | None, use_replay_script: bool) -> str:
    mode = (run_mode or "").strip().lower()
    if mode:
        if mode not in VALID_RUN_MODES:
            raise ValueError(f"Invalid run_mode: {run_mode}")
        return mode
    return RUN_MODE_AUTOMATIC if use_replay_script else RUN_MODE_TRAINING


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class StartRunRequest(BaseModel):
    task: str = ""
    success_criteria: str
    name: Optional[str] = None
    headless: bool = False
    max_steps: int = 100
    cdp_url: Optional[str] = None
    fresh_profile: bool = True
    website_id: Optional[str] = None
    website_task_id: Optional[str] = None
    source_run_id: Optional[str] = None
    use_replay_script: bool = False
    run_mode: Optional[str] = None

    @model_validator(mode="after")
    def _normalize_browser_overrides(self):
        cdp, fresh = normalize_browser_overrides(
            cdp_url=self.cdp_url,
            fresh_profile=self.fresh_profile,
        )
        self.cdp_url = cdp or None
        self.fresh_profile = fresh
        try:
            self.run_mode = resolve_run_mode(self.run_mode, self.use_replay_script)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        self.use_replay_script = self.run_mode == RUN_MODE_AUTOMATIC
        return self


class WebsiteCreateRequest(BaseModel):
    name: str
    url: str = ""
    description: str = ""
    context_prompt: str = ""


class WebsiteUpdateRequest(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    context_prompt: Optional[str] = None


class WebsiteTaskCreateRequest(BaseModel):
    task: str
    success_criteria: str
    name: Optional[str] = None
    headless: bool = False
    max_steps: int = 100
    cdp_url: Optional[str] = None
    fresh_profile: bool = True

    @model_validator(mode="after")
    def _normalize_browser_overrides(self):
        cdp, fresh = normalize_browser_overrides(
            cdp_url=self.cdp_url,
            fresh_profile=self.fresh_profile,
        )
        self.cdp_url = cdp or None
        self.fresh_profile = fresh
        return self


PROJECT_TESTS_PACK_KIND = "smart-automator.project-tests"
PROJECT_TESTS_PACK_VERSION = 1
PROJECT_PACK_KIND = "smart-automator.project"
PROJECT_PACK_VERSION = 1


class ProjectTestExportItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task: str
    success_criteria: str
    name: Optional[str] = None


class ProjectTestsPack(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int
    kind: str
    tests: list[ProjectTestExportItem]

    @model_validator(mode="after")
    def _validate_pack(self):
        if self.kind != PROJECT_TESTS_PACK_KIND:
            raise ValueError("Invalid pack kind")
        if self.version != PROJECT_TESTS_PACK_VERSION:
            raise ValueError("Unsupported pack version")
        if not self.tests:
            raise ValueError("At least one test is required")
        return self


class ProjectExportData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    url: str = ""
    context_prompt: str = ""


class ProjectPack(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int
    kind: str
    project: ProjectExportData
    tests: list[ProjectTestExportItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_pack(self):
        if self.kind != PROJECT_PACK_KIND:
            raise ValueError("Invalid pack kind")
        if self.version != PROJECT_PACK_VERSION:
            raise ValueError("Unsupported pack version")
        return self


class WebsiteTaskUpdateRequest(BaseModel):
    task: Optional[str] = None
    success_criteria: Optional[str] = None
    name: Optional[str] = None
    headless: Optional[bool] = None
    max_steps: Optional[int] = None
    cdp_url: Optional[str] = None
    fresh_profile: Optional[bool] = None

    @model_validator(mode="after")
    def _normalize_browser_overrides(self):
        if self.cdp_url is not None:
            cdp, fresh = normalize_browser_overrides(
                cdp_url=self.cdp_url,
                fresh_profile=self.fresh_profile if self.fresh_profile is not None else True,
            )
            self.cdp_url = cdp or None
            if self.fresh_profile is not None:
                self.fresh_profile = fresh
        return self


class RoleLlmUpdate(BaseModel):
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    openrouter_provider: Optional[str] = None


class ConfigUpdate(BaseModel):
    roles: Optional[dict[str, RoleLlmUpdate]] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    openrouter_provider: Optional[str] = None
    fresh_profile: Optional[bool] = None
    chrome_user_data: Optional[str] = None
    chrome_profile_directory: Optional[str] = None
    cdp_url: Optional[str] = None

    @model_validator(mode="after")
    def _normalize_browser_overrides(self):
        if self.cdp_url is not None:
            cdp, fresh = normalize_browser_overrides(
                cdp_url=self.cdp_url,
                fresh_profile=self.fresh_profile if self.fresh_profile is not None else True,
            )
            self.cdp_url = cdp
            if self.fresh_profile is not None:
                self.fresh_profile = fresh
        return self

class PricingEntryModel(BaseModel):
    provider: str
    model: str
    input: float
    output: float
    cache_read: float = 0.0


class ReplayUpdateRequest(BaseModel):
    replay_steps: list[dict[str, Any]] = Field(default_factory=list)
