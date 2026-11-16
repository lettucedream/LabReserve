import json
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request as ServiceRequest, urlopen
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from labreserve_auth import COOKIE_NAME, Principal, require_admin, require_user
from .accounts import (AccountRecord, AuthThrottle, DUMMY_PASSWORD_HASH, SessionRecord, digest,
                       hash_password, issue_session, new_recovery, password_error, recovery_digest, revoke_sessions, verify_password)
from .database import SessionLocal, get_session

router = APIRouter(prefix="/auth", tags=["Account"])
DbSession = Annotated[Session, Depends(get_session)]
User = Annotated[Principal, Depends(require_user)]
Admin = Annotated[Principal, Depends(require_admin)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


def username_value(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,31}", value):
        raise ValueError("Lo username deve avere da 3 a 32 lettere minuscole, numeri, punti, trattini o underscore")
    return value


class Credentials(Input):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value):
        return username_value(value)


class Registration(Credentials):
    password: str = Field(min_length=8, max_length=128)


class Recovery(Input):
    recovery_code: str = Field(min_length=20, max_length=100)
    new_password: str = Field(min_length=8, max_length=128)
    new_username: str | None = Field(default=None, max_length=64)

    @field_validator("new_username")
    @classmethod
    def validate_username(cls, value):
        return username_value(value) if value else None


class ProfileUpdate(Input):
    current_password: str = Field(min_length=1, max_length=128)
    new_username: str | None = Field(default=None, max_length=64)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("new_username")
    @classmethod
    def validate_username(cls, value):
        return username_value(value) if value else None


class PasswordCheck(Input):
    current_password: str = Field(min_length=1, max_length=128)


class AdminReset(Input):
    admin_password: str = Field(min_length=1, max_length=128)
    new_username: str | None = Field(default=None, max_length=64)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_username")
    @classmethod
    def validate_username(cls, value):
        return username_value(value) if value else None


class AdminCreate(Registration):
    
    user_id: str | None = Field(default=None, min_length=1, max_length=120)


class AdminDelete(Input):
    admin_password: str = Field(min_length=1, max_length=128)


def validate_new_password(password, username):
    error = password_error(password)
    if error:
        raise HTTPException(422, error)
    if password.casefold() == username:
        raise HTTPException(422, "La password deve essere diversa dallo username.")


def validate_new_username(username, role="user", test=False):
    if role != "admin" and username == "admin" or username.startswith("check-") and not test:
        raise HTTPException(409, "Username non disponibile.")


def account_info(account):
    return {"id": str(account.id), "user_id": account.user_id, "username": account.username,
            "role": account.role, "initialized": account.password_hash is not None}


def auth_result(account, csrf, recovery=None):
    return {"user": account_info(account), "csrf_token": csrf, "recovery_code": recovery}


def set_cookie(response, token):
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true",
                        samesite="strict", max_age=8 * 3600, path="/")
    response.headers["Cache-Control"] = "no-store"


def check_origin(request):
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        expected_scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        if parsed.netloc.lower() != request.headers.get("host", "").lower() or parsed.scheme != expected_scheme:
            raise HTTPException(403, "Origine della richiesta non consentita.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Origine della richiesta non consentita.")


def throttle(request, operation, name="", limit=30):
    
    key = digest(operation + ":" + (name or (request.client.host if request.client else "local")))
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        session.execute(insert(AuthThrottle).values(key=key, attempts=0, window_until=now + timedelta(minutes=5)).on_conflict_do_nothing())
        row = session.scalar(select(AuthThrottle).where(AuthThrottle.key == key).with_for_update())
        if row.window_until <= now:
            row.attempts, row.window_until = 0, now + timedelta(minutes=5)
        if row.attempts >= limit:
            raise HTTPException(429, "Troppi tentativi. Riprova tra cinque minuti.", headers={"Retry-After": "300"})
        row.attempts += 1


def commit_unique(session):
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Username non disponibile.") from None


@router.post("/register", status_code=201)
def register(payload: Registration, request: Request, response: Response, session: DbSession):
    check_origin(request)
    throttle(request, "register", limit=50)
    validate_new_username(payload.username)
    validate_new_password(payload.password, payload.username)
    account = AccountRecord(id=uuid4(), user_id=str(uuid4()), username=payload.username, role="user", password_hash=hash_password(payload.password))
    recovery = new_recovery(account)
    session.add(account)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Username non disponibile.") from None
    token, csrf = issue_session(session, account)
    commit_unique(session)
    set_cookie(response, token)
    return auth_result(account, csrf, recovery)


@router.post("/login")
def login(payload: Credentials, request: Request, response: Response, session: DbSession):
    check_origin(request)
    throttle(request, "login-ip", limit=150)
    throttle(request, "login-name", payload.username, limit=15)
    account = session.scalar(select(AccountRecord).where(AccountRecord.username == payload.username, AccountRecord.deleted_at.is_(None)).with_for_update())
    encoded = account.password_hash if account and account.password_hash else DUMMY_PASSWORD_HASH
    if not verify_password(payload.password, encoded) or account is None or account.password_hash is None:
        raise HTTPException(401, "Username o password non corretti.")
    recovery = new_recovery(account) if account.recovery_hash is None else None
    token, csrf = issue_session(session, account)
    session.commit()
    set_cookie(response, token)
    return auth_result(account, csrf, recovery)


@router.get("/session")
def current_session(user: User, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"user": {"id": user.id, "user_id": user.user_id, "username": user.username, "role": user.role, "initialized": True}, "csrf_token": user.csrf_token}


@router.post("/logout")
def logout(request: Request, response: Response, user: User, session: DbSession):
    record = session.get(SessionRecord, digest(request.cookies[COOKIE_NAME]))
    if record:
        session.delete(record)
    session.commit()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict", secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true")
    return {"message": "Disconnessione eseguita."}


@router.patch("/account")
def update_account(payload: ProfileUpdate, response: Response, user: User, session: DbSession):
    account = session.scalar(select(AccountRecord).where(AccountRecord.id == UUID(user.id)).with_for_update())
    if account is None or account.deleted_at is not None:
        raise HTTPException(401, "Sessione scaduta. Accedi di nuovo.")
    if not verify_password(payload.current_password, account.password_hash):
        raise HTTPException(403, "Password attuale non corretta.")
    if payload.new_username:
        validate_new_username(payload.new_username, account.role)
        account.username = payload.new_username
    if payload.new_password:
        validate_new_password(payload.new_password, account.username)
        account.password_hash = hash_password(payload.new_password)
    revoke_sessions(session, account.id)
    token, csrf = issue_session(session, account)
    commit_unique(session)
    set_cookie(response, token)
    return auth_result(account, csrf)


@router.post("/recovery-code")
def rotate_recovery(payload: PasswordCheck, user: User, session: DbSession):
    account = session.scalar(select(AccountRecord).where(AccountRecord.id == UUID(user.id)).with_for_update())
    if account is None or account.deleted_at is not None:
        raise HTTPException(401, "Sessione scaduta. Accedi di nuovo.")
    if not verify_password(payload.current_password, account.password_hash):
        raise HTTPException(403, "Password attuale non corretta.")
    code = new_recovery(account)
    session.commit()
    return {"recovery_code": code}


@router.post("/recover")
def recover(payload: Recovery, request: Request, session: DbSession):
    check_origin(request)
    throttle(request, "recover", limit=15)
    account = session.scalar(select(AccountRecord).where(AccountRecord.recovery_hash == recovery_digest(payload.recovery_code), AccountRecord.deleted_at.is_(None)).with_for_update())
    if account is None:
        raise HTTPException(400, "Codice di recupero non valido o gia utilizzato.")
    username = payload.new_username or account.username
    validate_new_username(username, account.role)
    validate_new_password(payload.new_password, username)
    account.username, account.password_hash = username, hash_password(payload.new_password)
    code = new_recovery(account)
    revoke_sessions(session, account.id)
    commit_unique(session)
    return {"username": account.username, "recovery_code": code, "message": "Credenziali aggiornate. Puoi accedere con la nuova password."}


@router.get("/users")
def list_users(admin: Admin, session: DbSession, include_test: bool = False):
    query = select(AccountRecord).where(AccountRecord.deleted_at.is_(None))
    if not include_test:
        query = query.where(~AccountRecord.username.startswith("check-"))
    return [account_info(account) for account in session.scalars(query.order_by(AccountRecord.username)).all()]


@router.post("/users", status_code=201)
def create_user(payload: AdminCreate, admin: Admin, session: DbSession):
    validate_new_username(payload.username, test=True)
    validate_new_password(payload.password, payload.username)
    account = AccountRecord(id=uuid4(), user_id=payload.user_id or str(uuid4()), username=payload.username, role="user", password_hash=hash_password(payload.password))
    code = new_recovery(account)
    session.add(account)
    commit_unique(session)
    return {"user": account_info(account), "recovery_code": code}


@router.post("/users/{account_id}/reset")
def reset_user(account_id: UUID, payload: AdminReset, admin: Admin, session: DbSession):
    administrator = session.get(AccountRecord, UUID(admin.id))
    if not verify_password(payload.admin_password, administrator.password_hash):
        raise HTTPException(403, "Password amministratore non corretta.")
    account = session.scalar(select(AccountRecord).where(AccountRecord.id == account_id).with_for_update())
    if account is None or account.deleted_at is not None:
        raise HTTPException(404, "Account non trovato.")
    if account.role == "admin":
        raise HTTPException(403, "Per l'account amministratore usa le impostazioni del tuo account.")
    username = payload.new_username or account.username
    validate_new_username(username)
    validate_new_password(payload.new_password, username)
    account.username, account.password_hash = username, hash_password(payload.new_password)
    code = new_recovery(account)
    revoke_sessions(session, account.id)
    commit_unique(session)
    return {"user": account_info(account), "recovery_code": code}


@router.delete("/users/{account_id}", status_code=204)
def delete_user(account_id: UUID, payload: AdminDelete, request: Request, admin: Admin, session: DbSession):
    administrator = session.get(AccountRecord, UUID(admin.id))
    if not verify_password(payload.admin_password, administrator.password_hash):
        raise HTTPException(403, "Password amministratore non corretta.")
    account = session.scalar(select(AccountRecord).where(AccountRecord.id == account_id).with_for_update())
    if account is None:
        raise HTTPException(404, "Account non trovato.")
    if account.role == "admin":
        raise HTTPException(403, "L'account amministratore non può essere eliminato.")
    if account.deleted_at is not None:
        return Response(status_code=204)


    booking_url = os.getenv("BOOKING_SERVICE_URL", "http://booking:8000").rstrip("/")
    headers = {"Content-Type": "application/json", "Cookie": f"{COOKIE_NAME}={request.cookies[COOKIE_NAME]}",
               "X-CSRF-Token": request.headers["X-CSRF-Token"]}
    operation = ServiceRequest(booking_url + "/admin/deactivate-user", method="POST", headers=headers,
                               data=json.dumps({"user_id": account.user_id}).encode())
    try:
        with urlopen(operation, timeout=5) as result:
            if result.status != 200:
                raise HTTPException(503, "Eliminazione non completata. Riprova tra poco.")
    except (HTTPError, URLError, OSError):
        raise HTTPException(503, "Eliminazione non completata. Riprova tra poco.") from None
    revoke_sessions(session, account.id)
    account.deleted_at = datetime.now(UTC)
    account.password_hash = account.recovery_hash = None
    session.commit()
    return Response(status_code=204)
