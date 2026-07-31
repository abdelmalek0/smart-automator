from __future__ import annotations

from fastapi import Cookie, HTTPException, Request

from .stores import SessionStore, User, UserStore

SESSION_COOKIE_NAME = "sa_session"

_user_store: UserStore | None = None
_session_store: SessionStore | None = None


def user_store() -> UserStore:
    global _user_store
    if _user_store is None:
        _user_store = UserStore()
    return _user_store


def session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store


def resolve_user_from_session(session_id: str | None) -> User | None:
    if not session_id:
        return None
    session = session_store().get_session(session_id)
    if session is None:
        return None
    return user_store().get_by_id(session.user_id)


async def get_current_user(
    request: Request,
    sa_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> User:
    session_id = sa_session or request.cookies.get(SESSION_COOKIE_NAME)
    user = resolve_user_from_session(session_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def get_optional_user(
    request: Request,
    sa_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> User | None:
    session_id = sa_session or request.cookies.get(SESSION_COOKIE_NAME)
    return resolve_user_from_session(session_id)
