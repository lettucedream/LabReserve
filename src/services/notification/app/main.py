import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, TimeoutError as DatabaseTimeout
from sqlalchemy.orm import Session

from labreserve_observability.database import DatabaseCollector
from labreserve_observability.http import install_metrics
from labreserve_auth import Principal, own_record, own_user, require_user
from .database import SessionLocal, get_session
from .metrics import business_metrics
from .models import NotificationRecord, messaging_tables
from .schemas import Notification, ReadUpdate

app = FastAPI(title="LabReserve - Notification Service", version="development")
DbSession = Annotated[Session, Depends(get_session)]
User = Annotated[Principal, Depends(require_user)]
install_metrics(app, "notification", DatabaseCollector("notification", SessionLocal, messaging_tables, business_metrics))


@app.exception_handler(OperationalError)
@app.exception_handler(DatabaseTimeout)
async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).warning("Database non disponibile: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database temporaneamente non disponibile"})


@app.get("/health", tags=["Sistema"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "notification"}


@app.get("/ready", tags=["Sistema"])
def ready(session: DbSession) -> dict[str, str]:
    session.execute(select(1))
    return {"status": "ready", "database": "available"}


@app.get("/notifications", response_model=list[Notification], tags=["Notifiche"])
def list_notifications(session: DbSession, principal: User, user_id: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    unread_only: bool = False, limit: Annotated[int, Query(ge=1, le=200)] = 100):
    user = own_user(principal, user_id)
    query = select(NotificationRecord).where(NotificationRecord.user_id == user, NotificationRecord.deleted_at.is_(None))
    if unread_only:
        query = query.where(NotificationRecord.read_at.is_(None))
    return list(session.scalars(query.order_by(NotificationRecord.occurred_at.desc(), NotificationRecord.id).limit(limit)).all())


@app.get("/notifications/{notification_id}", response_model=Notification, tags=["Notifiche"])
def get_notification(notification_id: UUID, session: DbSession, principal: User):
    notification = own_record(principal, session.get(NotificationRecord, notification_id), "Notifica non trovata")
    if notification.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Notifica non trovata")
    return notification


@app.patch("/notifications/{notification_id}", response_model=Notification, tags=["Notifiche"])
def mark_read(notification_id: UUID, payload: ReadUpdate, session: DbSession, principal: User):
    notification = own_record(principal, session.get(NotificationRecord, notification_id, with_for_update=True), "Notifica non trovata")
    if notification.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Notifica non trovata")
    if payload.is_read and notification.read_at is None:
        notification.read_at = datetime.now(UTC)
    elif not payload.is_read:
        notification.read_at = None
    session.commit()
    return notification


@app.delete("/notifications/{notification_id}", status_code=204, tags=["Notifiche"])
def delete_notification(notification_id: UUID, session: DbSession, principal: User):
    notification = own_record(principal, session.get(NotificationRecord, notification_id, with_for_update=True), "Notifica non trovata")
    if notification.deleted_at is None:
        notification.deleted_at = datetime.now(UTC)
        session.commit()
    return Response(status_code=204)
