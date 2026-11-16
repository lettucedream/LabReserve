import hmac
import json
import os
from dataclasses import dataclass
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.request import Request as HttpRequest, urlopen

from fastapi import Depends, Header, HTTPException, Request, Security
from fastapi.security import APIKeyCookie

COOKIE_NAME = "labreserve_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
session_cookie = APIKeyCookie(name=COOKIE_NAME, auto_error=False)


@dataclass(frozen=True)
class Principal:
    id: str
    user_id: str
    username: str
    role: str
    csrf_token: str

    @classmethod
    def from_session(cls, data):
        user = data["user"]
        return cls(str(user["id"]), user["user_id"], user["username"], user["role"], data["csrf_token"])


def check_csrf(request, principal):
    if request.method not in SAFE_METHODS and not hmac.compare_digest(request.headers.get("X-CSRF-Token", "").encode(), principal.csrf_token.encode()):
        raise HTTPException(403, "Sessione non valida per questa operazione. Ricarica la pagina.")


def require_user(request: Request, token: Annotated[str | None, Security(session_cookie)] = None,
                 csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None) -> Principal:
    token = token or request.cookies.get(COOKIE_NAME, "")
    if not token or len(token) > 100:
        raise HTTPException(401, "Accedi per continuare.")
    
    resolver = getattr(request.app.state, "resolve_auth_session", None)
    if resolver:
        principal = resolver(token)
    else:
        endpoint = os.getenv("AUTH_SERVICE_URL", "http://availability:8000").rstrip("/") + "/auth/session"
        try:
            with urlopen(HttpRequest(endpoint, headers={"Cookie": f"{COOKIE_NAME}={token}", "Accept": "application/json"}), timeout=3) as response:
                principal = Principal.from_session(json.loads(response.read(8192)))
        except HTTPError as exc:
            if exc.code == 401:
                raise HTTPException(401, "Sessione scaduta. Accedi di nuovo.") from None
            raise HTTPException(503, "Autenticazione temporaneamente non disponibile.") from None
        except (URLError, OSError, ValueError, KeyError, TypeError):
            raise HTTPException(503, "Autenticazione temporaneamente non disponibile.") from None
    check_csrf(request, principal)
    return principal


def require_admin(principal: Annotated[Principal, Depends(require_user)]) -> Principal:
    if principal.role != "admin":
        raise HTTPException(403, "Questa operazione e riservata all'amministratore.")
    return principal


def own_user(principal, supplied=None):
    if supplied is not None and not supplied.strip():
        raise HTTPException(422, "user_id non puo essere vuoto")
    if supplied is not None and supplied.strip() != principal.user_id:
        raise HTTPException(403, "Puoi consultare soltanto i tuoi dati.")
    return principal.user_id


def own_record(principal, record, detail):
    
    if record is None or record.user_id != principal.user_id:
        raise HTTPException(404, detail)
    return record
