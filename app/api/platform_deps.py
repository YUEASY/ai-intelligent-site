"""Dependency that builds a store-backed Platform Adapter per tenant."""

import base64
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.config import Settings, get_settings
from app.database import tenant_session
from app.platform import PlatformAdapter
from app.shopify.oauth import TokenCipher
from app.shopify.products import ShopifyPlatformAdapterFactory


class PlatformAdapterFactory(Protocol):
    def __call__(self, tenant_id: UUID) -> PlatformAdapter: ...


def get_platform_adapter_factory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlatformAdapterFactory:
    try:
        encryption_key = base64.b64decode(
            settings.shopify_token_encryption_key.get_secret_value(),
            validate=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shopify token encryption is not configured",
        ) from exc
    return ShopifyPlatformAdapterFactory(
        session_factory=tenant_session,
        cipher=TokenCipher(encryption_key),
    )
