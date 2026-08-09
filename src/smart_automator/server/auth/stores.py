from __future__ import annotations

import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from ...db.engine import get_session
from ...db.models import SessionRow, UserRow
from .passwords import hash_password, verify_password

SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
# Avoid rewriting the session row on every authenticated request.
SESSION_TOUCH_INTERVAL_SECONDS = 60 * 60
_MAX_USERNAME_LENGTH = 64


@dataclass(frozen=True)
class User:
    id: str
    username: str
    created_at: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> User:
        return cls(
            id=str(data["id"]),
            username=str(data["username"]),
            created_at=float(data.get("created_at", 0)),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "created_at": self.created_at,
        }


@dataclass
class Session:
    session_id: str
    user_id: str
    created_at: float
    expires_at: float
    last_seen_at: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        return cls(
            session_id=str(data["session_id"]),
            user_id=str(data["user_id"]),
            created_at=float(data.get("created_at", 0)),
            expires_at=float(data.get("expires_at", 0)),
            last_seen_at=float(data.get("last_seen_at", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_seen_at": self.last_seen_at,
        }

    def is_expired(self, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        return current >= self.expires_at


def _user_from_row(row: UserRow) -> User:
    return User(id=row.id, username=row.username, created_at=row.created_at)


def _session_from_row(row: SessionRow) -> Session:
    return Session(
        session_id=row.session_id,
        user_id=row.user_id,
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_seen_at=row.last_seen_at,
    )


class UserStore:
    def __init__(self, path: Path | None = None) -> None:
        # path is ignored; kept for backward compatibility with tests.
        self._lock = threading.Lock()

    def has_users(self) -> bool:
        with self._lock:
            with get_session() as session:
                row = session.scalar(select(UserRow.id).limit(1))
                return row is not None

    def get_by_id(self, user_id: str) -> User | None:
        with self._lock:
            with get_session() as session:
                row = session.get(UserRow, user_id)
                return _user_from_row(row) if row is not None else None

    def get_by_username(self, username: str) -> tuple[User, str] | None:
        normalized = username.strip().lower()
        with self._lock:
            with get_session() as session:
                row = session.scalar(
                    select(UserRow).where(func.lower(UserRow.username) == normalized)
                )
                if row is None:
                    return None
                return _user_from_row(row), row.password_hash

    def create_user(
        self,
        username: str,
        password: str,
        *,
        allow_when_users_exist: bool = True,
    ) -> User:
        normalized = username.strip()
        if not normalized:
            raise ValueError("Username is required")
        if len(normalized) > _MAX_USERNAME_LENGTH:
            raise ValueError(f"Username must be at most {_MAX_USERNAME_LENGTH} characters")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        with self._lock:
            with get_session() as session:
                if session.scalar(select(UserRow.id).limit(1)) is not None and not allow_when_users_exist:
                    raise PermissionError("Registration is disabled")
                existing = session.scalar(
                    select(UserRow).where(func.lower(UserRow.username) == normalized.lower())
                )
                if existing is not None:
                    raise ValueError("Username already exists")
                user_id = str(uuid.uuid4())
                created_at = time.time()
                session.add(
                    UserRow(
                        id=user_id,
                        username=normalized,
                        password_hash=hash_password(password),
                        created_at=created_at,
                    )
                )
                return User(id=user_id, username=normalized, created_at=created_at)

    def verify_credentials(self, username: str, password: str) -> User | None:
        found = self.get_by_username(username)
        if not found:
            return None
        user, password_hash = found
        if not verify_password(password, password_hash):
            return None
        return user


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        # path is ignored; kept for backward compatibility with tests.
        self._lock = threading.Lock()

    def _prune_expired(self, now: float) -> None:
        with get_session() as session:
            expired = session.scalars(
                select(SessionRow).where(SessionRow.expires_at <= now)
            ).all()
            for row in expired:
                session.delete(row)

    def create_session(self, user_id: str) -> Session:
        now = time.time()
        session_obj = Session(
            session_id=secrets.token_urlsafe(32),
            user_id=user_id,
            created_at=now,
            expires_at=now + SESSION_TTL_SECONDS,
            last_seen_at=now,
        )
        with self._lock:
            self._prune_expired(now)
            with get_session() as session:
                session.add(
                    SessionRow(
                        session_id=session_obj.session_id,
                        user_id=session_obj.user_id,
                        created_at=session_obj.created_at,
                        expires_at=session_obj.expires_at,
                        last_seen_at=session_obj.last_seen_at,
                    )
                )
        return session_obj

    def get_session(self, session_id: str) -> Session | None:
        if not session_id:
            return None
        now = time.time()
        with self._lock:
            with get_session() as session:
                row = session.get(SessionRow, session_id)
                if row is None:
                    return None
                if row.expires_at <= now:
                    session.delete(row)
                    return None
                session_obj = _session_from_row(row)
                if now - session_obj.last_seen_at >= SESSION_TOUCH_INTERVAL_SECONDS:
                    row.last_seen_at = now
                    row.expires_at = now + SESSION_TTL_SECONDS
                    session_obj.last_seen_at = now
                    session_obj.expires_at = now + SESSION_TTL_SECONDS
                return session_obj

    def delete_session(self, session_id: str) -> None:
        now = time.time()
        with self._lock:
            self._prune_expired(now)
            with get_session() as session:
                session.execute(delete(SessionRow).where(SessionRow.session_id == session_id))
