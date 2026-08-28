from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.auth import create_access_token, verify_password
from app.config import Settings, get_settings
from app.database import tenant_session_scope
from app.dependencies import RequestContext, get_request_context
from app.models import AdminUser
from app.schemas import AdminRead, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    request: LoginRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    invalid_login = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid tenant, email, or password",
    )
    with tenant_session_scope(request.tenant_id) as session:
        admin = session.scalar(
            select(AdminUser).where(AdminUser.email == request.email)
        )
        if (
            admin is None
            or not admin.is_active
            or not verify_password(request.password, admin.password_hash)
        ):
            raise invalid_login
        token = create_access_token(
            admin_id=admin.id,
            tenant_id=admin.tenant_id,
            settings=settings,
        )
    return TokenResponse(access_token=token)


@router.get("/me", response_model=AdminRead)
def me(
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> AdminRead:
    return AdminRead(
        id=context.admin.id,
        tenant_id=context.admin.tenant_id,
        email=context.admin.email,
    )
