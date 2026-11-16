import hashlib
import hmac
import json
import os
import secrets
import sys
import unicodedata
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, delete, func, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from labreserve_auth import Principal
from .database import Base, SessionLocal

ITERATIONS = 600_000


class AccountRecord(Base):
    __tablename__ = "accounts"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(120), unique=True)
    username: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(10), server_default="user")
    password_hash: Mapped[str | None] = mapped_column(String(256))
    recovery_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="ck_accounts_role"),
        Index("uq_accounts_one_admin", "role", unique=True, postgresql_where=text("role = 'admin'")),
        Index("uq_accounts_active_username", "username", unique=True, postgresql_where=text("deleted_at IS NULL")),
    )


class SessionRecord(Base):
    __tablename__ = "account_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthThrottle(Base):
    __tablename__ = "auth_throttle"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int]
    window_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_password(value):
    return unicodedata.normalize("NFC", value)


def password_error(value):
    value = normalize_password(value)
    if not (8 <= len(value) <= 128
            and any(unicodedata.category(char) == "Lu" for char in value)
            and any(unicodedata.category(char) == "Nd" for char in value)
            and any(unicodedata.category(char)[0] in {"P", "S"} for char in value)):
        return "Usa da 8 a 128 caratteri, con almeno una maiuscola, un numero e un simbolo speciale."
    return None


def hash_password(password):
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", normalize_password(password).encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password, encoded):
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 600_000 <= int(rounds) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", normalize_password(password).encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError):
        return False


DUMMY_PASSWORD_HASH = "pbkdf2_sha256$600000$" + "00" * 16 + "$" + "00" * 32


def new_recovery(account):
    code = secrets.token_hex(20)
    account.recovery_hash = digest(code)
    return "-".join(code[index:index + 8] for index in range(0, len(code), 8))


def recovery_digest(code):
    return digest(code.strip().lower().replace("-", "").replace(" ", ""))


def revoke_sessions(session, account_id):
    with session.no_autoflush:
        session.execute(delete(SessionRecord).where(SessionRecord.account_id == account_id))


def issue_session(session, account, hours=8):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    with session.no_autoflush:
        session.execute(delete(SessionRecord).where(SessionRecord.expires_at <= now))
    session.add(SessionRecord(token_hash=digest(token), account_id=account.id, csrf_token=csrf, expires_at=now + timedelta(hours=hours)))
    return token, csrf


def resolve_session(token):
    with SessionLocal() as session:
        row = session.execute(select(AccountRecord, SessionRecord).join(SessionRecord, AccountRecord.id == SessionRecord.account_id)
            .where(SessionRecord.token_hash == digest(token), SessionRecord.expires_at > datetime.now(UTC))).first()
        if row is None or row[0].password_hash is None or row[0].deleted_at is not None:
            raise HTTPException(401, "Sessione scaduta. Accedi di nuovo.")
        account, auth_session = row
        return Principal(str(account.id), account.user_id, account.username, account.role, auth_session.csrf_token)


def seed_accounts():
    with SessionLocal.begin() as session:
        session.execute(text("SELECT pg_advisory_xact_lock(28110402)"))
        if session.scalar(select(AccountRecord.id).where(AccountRecord.role == "admin")) is None:
            password = os.getenv("ADMIN_INITIAL_PASSWORD", "")
            if password_error(password) or password.startswith("replace_with_"):
                raise RuntimeError("Impostare una ADMIN_INITIAL_PASSWORD valida nell'ambiente del container di inizializzazione")
            session.add(AccountRecord(user_id=str(uuid4()), username="admin", role="admin", password_hash=hash_password(password)))
        
        for username in ("federico", "anna", "bruno", "carla"):
            if session.scalar(select(AccountRecord.id).where(AccountRecord.user_id == username)) is None:
                session.add(AccountRecord(user_id=username, username=username, role="user", password_hash=None))


def operator_command(command):
    with SessionLocal.begin() as session:
        account = session.scalar(select(AccountRecord).where(AccountRecord.role == "admin").with_for_update())
        if account is None:
            raise RuntimeError("Account admin non inizializzato")
        if command == "reset-admin":
            password = "A7!" + secrets.token_urlsafe(24)
            account.username, account.password_hash = "admin", hash_password(password)
            recovery = new_recovery(account)
            revoke_sessions(session, account.id)
            result = {"username": account.username, "password": password, "recovery_code": recovery}
        else:
            raise ValueError("Comando operatore sconosciuto")
    print(json.dumps(result))


if __name__ == "__main__":
    operator_command(sys.argv[1])
