from __future__ import annotations

import os

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response

from ..models import LoginRequest, RegisterRequest
from .dependencies import SESSION_COOKIE_NAME, get_current_user, get_optional_user, session_store, user_store
from .stores import SESSION_TTL_SECONDS, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _cookie_secure() -> bool:
    return os.getenv("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=_cookie_secure(),
        httponly=True,
        samesite="lax",
    )


def _registration_open() -> bool:
    # Default on; set ALLOW_OPEN_REGISTER=false to lock signup after first user.
    return os.getenv("ALLOW_OPEN_REGISTER", "true").lower() not in {"0", "false", "no"}


@router.get("/setup")
async def auth_setup() -> dict[str, bool]:
    try:
        needs = not user_store().has_users()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "needs_registration": needs,
        "registration_open": needs or _registration_open(),
    }


@router.post("/register", status_code=201)
async def register(req: RegisterRequest, response: Response) -> dict:
    try:
        user = user_store().create_user(
            req.username,
            req.password,
            allow_when_users_exist=_registration_open(),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    session = session_store().create_session(user.id)
    _set_session_cookie(response, session.session_id)
    return {"user": user.to_public_dict()}


@router.post("/login")
async def login(req: LoginRequest, response: Response) -> dict:
    try:
        user = user_store().verify_credentials(req.username, req.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    session = session_store().create_session(user.id)
    _set_session_cookie(response, session.session_id)
    return {"user": user.to_public_dict()}


@router.post("/logout")
async def logout(
    response: Response,
    sa_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    _user: User | None = Depends(get_optional_user),
) -> dict[str, bool]:
    if sa_session:
        session_store().delete_session(sa_session)
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return {"user": user.to_public_dict()}
