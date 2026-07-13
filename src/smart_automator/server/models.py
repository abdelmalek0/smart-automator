from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class StartRunRequest(BaseModel):
    task: str
    headless: bool = False
    max_steps: int = 100
    cdp_url: Optional[str] = None
    fresh_profile: bool = False
    website_id: Optional[str] = None


class WebsiteCreateRequest(BaseModel):
    name: str
    url: str = ""
    context_prompt: str = ""


class WebsiteUpdateRequest(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    context_prompt: Optional[str] = None


class WebsiteTaskCreateRequest(BaseModel):
    task: str
    headless: bool = False
    max_steps: int = 100
    cdp_url: Optional[str] = None
    fresh_profile: bool = False


class WebsiteTaskUpdateRequest(BaseModel):
    task: Optional[str] = None
    headless: Optional[bool] = None
    max_steps: Optional[int] = None
    cdp_url: Optional[str] = None
    fresh_profile: Optional[bool] = None


class ConfigUpdate(BaseModel):
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    fresh_profile: Optional[bool] = None


class PricingEntryModel(BaseModel):
    provider: str
    model: str
    input: float
    output: float
    cache_read: float = 0.0
