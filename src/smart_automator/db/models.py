from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float)


class SessionRow(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    created_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    last_seen_at: Mapped[float] = mapped_column(Float)


class WebsiteRow(Base):
    __tablename__ = "websites"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(String, default="")
    context_prompt: Mapped[str] = mapped_column(String, default="")

    tasks: Mapped[list[WebsiteTaskRow]] = relationship(
        back_populates="website",
        cascade="all, delete-orphan",
        order_by="WebsiteTaskRow.id",
    )


class WebsiteTaskRow(Base):
    __tablename__ = "website_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    website_id: Mapped[str] = mapped_column(String, ForeignKey("websites.id"), index=True)
    task: Mapped[str] = mapped_column(String)
    success_criteria: Mapped[str] = mapped_column(String, default="")
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    headless: Mapped[bool] = mapped_column(Boolean, default=False)
    max_steps: Mapped[int] = mapped_column(Integer, default=100)
    cdp_url: Mapped[str | None] = mapped_column(String, nullable=True)
    fresh_profile: Mapped[bool] = mapped_column(Boolean, default=True)
    last_trained_run_id: Mapped[str | None] = mapped_column(String, nullable=True)

    website: Mapped[WebsiteRow] = relationship(back_populates="tasks")


class RunRow(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    started_at: Mapped[float] = mapped_column(Float, index=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)


class WorkerTokenRow(Base):
    __tablename__ = "worker_tokens"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True, unique=True)
    created_at: Mapped[float] = mapped_column(Float)


class UserLlmPrefsRow(Base):
    __tablename__ = "user_llm_prefs"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String, default="groq")
    models: Mapped[dict] = mapped_column(JSON, default=dict)
    api_keys: Mapped[dict] = mapped_column(JSON, default=dict)
    openrouter_provider: Mapped[str] = mapped_column(String, default="")
    roles: Mapped[dict] = mapped_column(JSON, default=dict)


class LlmCatalogRow(Base):
    __tablename__ = "llm_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PricingEntryRow(Base):
    __tablename__ = "pricing_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, index=True)
    model: Mapped[str] = mapped_column(String, index=True)
    input_price: Mapped[float] = mapped_column(Float, default=0.0)
    output_price: Mapped[float] = mapped_column(Float, default=0.0)
    cache_read: Mapped[float] = mapped_column(Float, default=0.0)
