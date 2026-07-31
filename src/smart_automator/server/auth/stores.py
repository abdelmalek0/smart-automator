from __future__ import annotations

import json
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import paths
from .passwords import hash_password, verify_password

SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
# Avoid rewriting sessions.json on every authenticated request.
SESSION_TOUCH_INTERVAL_SECONDS = 60 * 60
_MAX_USERNAME_LENGTH = 64


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


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


class UserStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or paths.USERS_FILE
        self._lock = threading.Lock()

    def _load_raw(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            # Fail closed: a corrupt users file must not look like "no users"
            # (which would reopen first-time registration).
            raise RuntimeError(f"Corrupt users file: {self._path}") from exc
        except OSError as exc:
            raise RuntimeError(f"Unable to read users file: {self._path}") from exc
        users = data.get("users", []) if isinstance(data, dict) else []
        if not isinstance(users, list):
            raise RuntimeError(f"Corrupt users file: {self._path}")
        return users

    def _save_raw(self, users: list[dict[str, Any]]) -> None:
        _atomic_write_json(self._path, {"users": users})

    def has_users(self) -> bool:
        with self._lock:
            return bool(self._load_raw())

    def get_by_id(self, user_id: str) -> User | None:
        with self._lock:
            for item in self._load_raw():
                if item.get("id") == user_id:
                    return User.from_dict(item)
        return None

    def get_by_username(self, username: str) -> tuple[User, str] | None:
        normalized = username.strip().lower()
        with self._lock:
            for item in self._load_raw():
                if str(item.get("username", "")).lower() == normalized:
                    return User.from_dict(item), str(item.get("password_hash", ""))
        return None

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
            raw = self._load_raw()
            if raw and not allow_when_users_exist:
                raise PermissionError("Registration is disabled")
            if any(str(item.get("username", "")).lower() == normalized.lower() for item in raw):
                raise ValueError("Username already exists")
            user = {
                "id": str(uuid.uuid4()),
                "username": normalized,
                "password_hash": hash_password(password),
                "created_at": time.time(),
            }
            raw.append(user)
            self._save_raw(raw)
            return User.from_dict(user)

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
        self._path = path or paths.SESSIONS_FILE
        self._lock = threading.Lock()

    def _load_raw(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return []
        sessions = data.get("sessions", []) if isinstance(data, dict) else []
        return sessions if isinstance(sessions, list) else []

    def _save_raw(self, sessions: list[dict[str, Any]]) -> None:
        _atomic_write_json(self._path, {"sessions": sessions})

    @staticmethod
    def _prune_expired(raw: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        for item in raw:
            try:
                expires_at = float(item.get("expires_at", 0))
            except (TypeError, ValueError):
                continue
            if expires_at > now:
                kept.append(item)
        return kept

    def create_session(self, user_id: str) -> Session:
        now = time.time()
        session = Session(
            session_id=secrets.token_urlsafe(32),
            user_id=user_id,
            created_at=now,
            expires_at=now + SESSION_TTL_SECONDS,
            last_seen_at=now,
        )
        with self._lock:
            raw = self._prune_expired(self._load_raw(), now)
            raw.append(session.to_dict())
            self._save_raw(raw)
        return session

    def get_session(self, session_id: str) -> Session | None:
        if not session_id:
            return None
        now = time.time()
        with self._lock:
            raw = self._load_raw()
            changed = False
            found: Session | None = None
            next_raw: list[dict[str, Any]] = []
            for item in raw:
                try:
                    session = Session.from_dict(item)
                except (KeyError, TypeError, ValueError):
                    changed = True
                    continue
                if session.is_expired(now):
                    changed = True
                    continue
                if session.session_id == session_id:
                    if now - session.last_seen_at >= SESSION_TOUCH_INTERVAL_SECONDS:
                        session.last_seen_at = now
                        session.expires_at = now + SESSION_TTL_SECONDS
                        changed = True
                    item = session.to_dict()
                    found = session
                next_raw.append(item)
            if changed:
                self._save_raw(next_raw)
            return found

    def delete_session(self, session_id: str) -> None:
        now = time.time()
        with self._lock:
            raw = self._load_raw()
            next_raw = [
                item
                for item in self._prune_expired(raw, now)
                if item.get("session_id") != session_id
            ]
            if len(next_raw) != len(raw):
                self._save_raw(next_raw)
