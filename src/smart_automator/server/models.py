from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from smart_automator.config import normalize_browser_overrides


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class StartRunRequest(BaseModel):
    task: str
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

    @model_validator(mode="after")
    def _normalize_browser_overrides(self):
        cdp, fresh = normalize_browser_overrides(
            cdp_url=self.cdp_url,
            fresh_profile=self.fresh_profile,
        )
        self.cdp_url = cdp or None
        self.fresh_profile = fresh
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
            cdp, _fresh = normalize_browser_overrides(
                cdp_url=self.cdp_url,
                fresh_profile=self.fresh_profile if self.fresh_profile is not None else False,
            )
            self.cdp_url = cdp or None
        return self


class ConfigUpdate(BaseModel):
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    fresh_profile: Optional[bool] = None
    chrome_user_data: Optional[str] = None
    chrome_profile_directory: Optional[str] = None
    cdp_url: Optional[str] = None

    @model_validator(mode="after")
    def _normalize_browser_overrides(self):
        if self.cdp_url is not None:
            cdp, _fresh = normalize_browser_overrides(
                cdp_url=self.cdp_url,
                fresh_profile=self.fresh_profile if self.fresh_profile is not None else False,
            )
            self.cdp_url = cdp
        return self

class PricingEntryModel(BaseModel):
    provider: str
    model: str
    input: float
    output: float
    cache_read: float = 0.0


class ReplayUpdateRequest(BaseModel):
    replay_steps: list[dict[str, Any]] = Field(default_factory=list)
