from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.auth import decode_access_token
from app.config import Settings, get_settings
from app.database import TenantSession, tenant_session_scope
from app.models import AdminUser

bearer = HTTPBearer(auto_error=False)


@dataclass
class RequestContext:
    tenant_id: UUID
    actor: str
    admin: AdminUser
    session: TenantSession


def get_request_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Generator[RequestContext, None, None]:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        claims = decode_access_token(credentials.credentials, settings)
    except ValueError as exc:
        raise unauthorized from exc

    with tenant_session_scope(claims.tenant_id) as session:
        admin = session.scalar(select(AdminUser).where(AdminUser.id == claims.admin_id))
        if admin is None or not admin.is_active:
            raise unauthorized
        yield RequestContext(
            tenant_id=claims.tenant_id,
            actor=admin.email,
            admin=admin,
            session=session,
        )
