import base64
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from starlette.responses import JSONResponse

from app.config import Settings, get_settings
from app.database import tenant_session
from app.dependencies import RequestContext, get_request_context
from app.models import ShopifyStore
from app.shopify.oauth import (
    HttpShopifyTokenClient,
    InvalidOAuthCallback,
    InvalidShopDomain,
    OAuthScopeMismatch,
    ShopifyOAuthAdapter,
    ShopifyTokenExchangeFailed,
    SqlAlchemyOAuthStates,
    SqlAlchemyShopifyInstallations,
    TokenCipher,
)
from app.shopify.webhook_service import (
    InvalidWebhookReplay,
    ShopifyWebhookService,
    WebhookEventNotFound,
)
from app.shopify.webhooks import (
    InvalidWebhookRequest,
    InvalidWebhookSignature,
    ShopifyWebhookAdapter,
    SqlAlchemyWebhookEvents,
    UnknownShopifyStore,
    WebhookDispatcher,
    WebhookDispatchFailed,
    WebhookReceiptStatus,
)

router = APIRouter(prefix="/shopify", tags=["shopify"])


class AuthorizationUrlRead(BaseModel):
    authorization_url: str


class ShopifyStoreRead(BaseModel):
    shop_domain: str
    status: str
    granted_scopes: list[str]


class DeadLetterRead(BaseModel):
    event_id: UUID
    webhook_id: str
    topic: str
    payload: dict[str, object]
    error_reason: str
    replay_count: int


class ReplayRead(BaseModel):
    event_id: UUID
    status: str
    replay_count: int


class WebhookAdapterFactory(Protocol):
    def __call__(self, tenant_id: UUID) -> ShopifyWebhookAdapter: ...


class CeleryWebhookDispatcher:
    def enqueue(self, event_id: UUID, tenant_id: UUID) -> None:
        from app.worker import process_shopify_webhook

        process_shopify_webhook.delay(str(event_id), str(tenant_id))


class DefaultWebhookAdapterFactory:
    def __init__(self, client_secret: str, dispatcher: WebhookDispatcher) -> None:
        self._client_secret = client_secret
        self._dispatcher = dispatcher

    def __call__(self, tenant_id: UUID) -> ShopifyWebhookAdapter:
        return ShopifyWebhookAdapter(
            client_secret=self._client_secret,
            events=SqlAlchemyWebhookEvents(
                tenant_id=tenant_id,
                session_factory=lambda: tenant_session(tenant_id),
            ),
            dispatcher=self._dispatcher,
        )


def get_shopify_oauth_adapter(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ShopifyOAuthAdapter:
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
    return ShopifyOAuthAdapter(
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret.get_secret_value(),
        redirect_uri=settings.shopify_redirect_uri,
        cipher=TokenCipher(encryption_key),
        states=SqlAlchemyOAuthStates(tenant_session),
        token_client=HttpShopifyTokenClient(
            client_id=settings.shopify_client_id,
            client_secret=settings.shopify_client_secret.get_secret_value(),
        ),
        installations=SqlAlchemyShopifyInstallations(tenant_session),
    )


def get_shopify_webhook_dispatcher() -> WebhookDispatcher:
    return CeleryWebhookDispatcher()


def get_shopify_webhook_adapter_factory(
    settings: Annotated[Settings, Depends(get_settings)],
    dispatcher: Annotated[
        WebhookDispatcher,
        Depends(get_shopify_webhook_dispatcher),
    ],
) -> WebhookAdapterFactory:
    return DefaultWebhookAdapterFactory(
        settings.shopify_client_secret.get_secret_value(),
        dispatcher,
    )


@router.get("/oauth/authorize", response_model=AuthorizationUrlRead)
def authorize_shopify(
    shop_domain: str,
    context: Annotated[RequestContext, Depends(get_request_context)],
    oauth: Annotated[ShopifyOAuthAdapter, Depends(get_shopify_oauth_adapter)],
) -> AuthorizationUrlRead:
    try:
        authorization_url = oauth.begin(
            tenant_id=context.tenant_id,
            shop_domain=shop_domain,
        )
    except InvalidShopDomain as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AuthorizationUrlRead(authorization_url=authorization_url)


@router.get("/oauth/callback", response_model=ShopifyStoreRead)
def shopify_oauth_callback(
    request: Request,
    oauth: Annotated[ShopifyOAuthAdapter, Depends(get_shopify_oauth_adapter)],
) -> ShopifyStoreRead:
    try:
        connected = oauth.complete(dict(request.query_params))
    except InvalidShopDomain as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (InvalidOAuthCallback, OAuthScopeMismatch) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ShopifyTokenExchangeFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Shopify authorization could not be completed",
        ) from exc
    return ShopifyStoreRead(
        shop_domain=connected.shop_domain,
        status="connected",
        granted_scopes=sorted(connected.granted_scopes),
    )


@router.get("/stores", response_model=list[ShopifyStoreRead])
def list_shopify_stores(
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[ShopifyStoreRead]:
    stores = context.session.scalars(
        select(ShopifyStore).order_by(ShopifyStore.shop_domain)
    )
    return [
        ShopifyStoreRead(
            shop_domain=store.shop_domain,
            status=store.status,
            granted_scopes=sorted(store.granted_scopes),
        )
        for store in stores
    ]


@router.post("/webhooks/ingress/{tenant_id}")
async def receive_shopify_webhook(
    tenant_id: UUID,
    request: Request,
    adapter_factory: Annotated[
        WebhookAdapterFactory,
        Depends(get_shopify_webhook_adapter_factory),
    ],
) -> JSONResponse:
    adapter = adapter_factory(tenant_id)
    try:
        receipt = adapter.receive(
            tenant_id=tenant_id,
            body=await request.body(),
            headers=request.headers,
        )
    except InvalidWebhookSignature as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except InvalidWebhookRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownShopifyStore as exc:
        raise HTTPException(status_code=404, detail="Shopify store not found") from exc
    except WebhookDispatchFailed as exc:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "event_id": str(exc.event_id),
                "status": "dead_letter",
            },
        )

    response_status = (
        status.HTTP_202_ACCEPTED
        if receipt.status is WebhookReceiptStatus.ACCEPTED
        else status.HTTP_200_OK
    )
    return JSONResponse(
        status_code=response_status,
        content={
            "event_id": str(receipt.event_id),
            "status": receipt.status.value,
        },
    )


@router.get("/webhooks/dead-letters", response_model=list[DeadLetterRead])
def list_shopify_dead_letters(
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[DeadLetterRead]:
    events = ShopifyWebhookService(context.session).list_dead_letters()
    return [
        DeadLetterRead(
            event_id=event.id,
            webhook_id=event.webhook_id,
            topic=event.topic,
            payload=event.payload,
            error_reason=event.error_reason or "Unknown error",
            replay_count=event.replay_count,
        )
        for event in events
    ]


@router.post(
    "/webhooks/{event_id}/replay",
    response_model=ReplayRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def replay_shopify_webhook(
    event_id: UUID,
    context: Annotated[RequestContext, Depends(get_request_context)],
    dispatcher: Annotated[
        WebhookDispatcher,
        Depends(get_shopify_webhook_dispatcher),
    ],
) -> ReplayRead:
    service = ShopifyWebhookService(context.session)
    try:
        event = service.replay(event_id)
        context.session.commit()
        dispatcher.enqueue(event.id, context.tenant_id)
    except WebhookEventNotFound as exc:
        raise HTTPException(status_code=404, detail="Webhook event not found") from exc
    except InvalidWebhookReplay as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        service.mark_dead_letter(
            event_id, f"Replay dispatch failed: {type(exc).__name__}"
        )
        context.session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook replay could not be dispatched",
        ) from exc
    return ReplayRead(
        event_id=event.id,
        status=event.status,
        replay_count=event.replay_count,
    )
