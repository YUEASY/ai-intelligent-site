import hashlib
import hmac
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from app.api.shopify import (
    get_shopify_oauth_adapter,
    get_shopify_webhook_adapter_factory,
    get_shopify_webhook_dispatcher,
    router,
)
from app.database import Base, TenantSession
from app.dependencies import RequestContext, get_request_context
from app.models import AdminUser, ShopifyStore, ShopifyWebhookEvent
from app.shopify.oauth import (
    ShopifyOAuthAdapter,
    ShopifyToken,
    SqlAlchemyOAuthStates,
    SqlAlchemyShopifyInstallations,
    TokenCipher,
)
from app.shopify.webhooks import ShopifyWebhookAdapter, SqlAlchemyWebhookEvents

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
CLIENT_SECRET = "oauth-client-secret"


class FakeTokenClient:
    def exchange(self, shop_domain: str, code: str) -> ShopifyToken:
        assert shop_domain == "merchant.myshopify.com"
        assert code == "one-time-code"
        return ShopifyToken(
            access_token="shpat_not_returned_by_the_api",
            granted_scopes=frozenset({"write_products", "write_content"}),
        )


def _callback_params(state: str) -> dict[str, str]:
    params = {
        "code": "one-time-code",
        "shop": "merchant.myshopify.com",
        "state": state,
        "timestamp": "1787932800",
    }
    message = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    params["hmac"] = hmac.new(
        CLIENT_SECRET.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return params


def test_oauth_connects_store_and_admin_api_exposes_only_connection_status() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def session_factory(tenant_id: UUID) -> TenantSession:
        return TenantSession(bind=engine, expire_on_commit=False, tenant_id=tenant_id)

    oauth_adapter = ShopifyOAuthAdapter(
        client_id="shopify-client-id",
        client_secret=CLIENT_SECRET,
        redirect_uri="https://platform.example.com/api/v1/shopify/oauth/callback",
        cipher=TokenCipher(bytes(range(32))),
        states=SqlAlchemyOAuthStates(session_factory),
        token_client=FakeTokenClient(),
        installations=SqlAlchemyShopifyInstallations(session_factory),
    )
    admin = AdminUser(
        id=uuid4(),
        tenant_id=TENANT_ID,
        email="admin@example.com",
        password_hash="unused",
    )

    def request_context() -> Iterator[RequestContext]:
        with session_factory(TENANT_ID) as session:
            yield RequestContext(
                tenant_id=TENANT_ID,
                actor=admin.email,
                admin=admin,
                session=session,
            )

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_request_context] = request_context
    app.dependency_overrides[get_shopify_oauth_adapter] = lambda: oauth_adapter
    client = TestClient(app)

    authorization = client.get(
        "/api/v1/shopify/oauth/authorize",
        params={"shop_domain": "merchant.myshopify.com"},
    )
    assert authorization.status_code == 200
    authorization_url = authorization.json()["authorization_url"]
    state = parse_qs(urlparse(authorization_url).query)["state"][0]

    callback = client.get(
        "/api/v1/shopify/oauth/callback",
        params=_callback_params(state),
    )
    assert callback.status_code == 200
    assert callback.json() == {
        "shop_domain": "merchant.myshopify.com",
        "status": "connected",
        "granted_scopes": ["write_content", "write_products"],
    }

    stores = client.get("/api/v1/shopify/stores")
    assert stores.status_code == 200
    response_text = stores.text.lower()
    assert "token" not in response_text
    assert stores.json() == [
        {
            "shop_domain": "merchant.myshopify.com",
            "status": "connected",
            "granted_scopes": ["write_content", "write_products"],
        }
    ]


class RecordingWebhookDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    def enqueue(self, event_id: UUID, tenant_id: UUID) -> None:
        self.calls.append((event_id, tenant_id))


def _webhook_signature(body: bytes) -> str:
    import base64

    digest = hmac.new(CLIENT_SECRET.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def test_webhook_endpoint_verifies_hmac_and_deduplicates_before_dispatch() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def session_factory(tenant_id: UUID) -> TenantSession:
        return TenantSession(bind=engine, expire_on_commit=False, tenant_id=tenant_id)

    with session_factory(TENANT_ID) as session:
        session.add(
            ShopifyStore(
                tenant_id=TENANT_ID,
                shop_domain="merchant.myshopify.com",
                status="connected",
                encrypted_access_token=b"encrypted",
                access_token_nonce=b"nonce",
                granted_scopes=["write_content", "write_products"],
            )
        )
        session.commit()

    dispatcher = RecordingWebhookDispatcher()

    def adapter_factory(tenant_id: UUID) -> ShopifyWebhookAdapter:
        return ShopifyWebhookAdapter(
            client_secret=CLIENT_SECRET,
            events=SqlAlchemyWebhookEvents(
                tenant_id=tenant_id,
                session_factory=lambda: session_factory(tenant_id),
            ),
            dispatcher=dispatcher,
        )

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_shopify_webhook_adapter_factory] = lambda: (
        adapter_factory
    )
    client = TestClient(app)
    body = b'{"id":42}'
    headers = {
        "X-Shopify-Hmac-Sha256": _webhook_signature(body),
        "X-Shopify-Webhook-Id": "webhook-123",
        "X-Shopify-Shop-Domain": "merchant.myshopify.com",
        "X-Shopify-Topic": "products/update",
        "X-Shopify-API-Version": "2026-07",
    }
    url = f"/api/v1/shopify/webhooks/ingress/{TENANT_ID}"

    invalid = client.post(
        url,
        content=body,
        headers={**headers, "X-Shopify-Hmac-Sha256": "invalid"},
    )
    assert invalid.status_code == 401

    first = client.post(url, content=body, headers=headers)
    duplicate = client.post(url, content=body, headers=headers)

    assert first.status_code == 202
    assert first.json()["status"] == "accepted"
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert len(dispatcher.calls) == 1
    with session_factory(TENANT_ID) as session:
        assert (
            session.scalar(select(func.count()).select_from(ShopifyWebhookEvent)) == 1
        )


class FailingWebhookDispatcher:
    def enqueue(self, event_id: UUID, tenant_id: UUID) -> None:
        raise ConnectionError("broker unavailable")


def test_dead_letter_is_visible_with_payload_and_can_be_replayed() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def session_factory(tenant_id: UUID) -> TenantSession:
        return TenantSession(bind=engine, expire_on_commit=False, tenant_id=tenant_id)

    with session_factory(TENANT_ID) as session:
        session.add(
            ShopifyStore(
                tenant_id=TENANT_ID,
                shop_domain="merchant.myshopify.com",
                status="connected",
                encrypted_access_token=b"encrypted",
                access_token_nonce=b"nonce",
                granted_scopes=["write_content", "write_products"],
            )
        )
        session.commit()

    def failing_adapter_factory(tenant_id: UUID) -> ShopifyWebhookAdapter:
        return ShopifyWebhookAdapter(
            client_secret=CLIENT_SECRET,
            events=SqlAlchemyWebhookEvents(
                tenant_id=tenant_id,
                session_factory=lambda: session_factory(tenant_id),
            ),
            dispatcher=FailingWebhookDispatcher(),
        )

    replay_dispatcher = RecordingWebhookDispatcher()
    admin = AdminUser(
        id=uuid4(),
        tenant_id=TENANT_ID,
        email="admin@example.com",
        password_hash="unused",
    )

    def request_context() -> Iterator[RequestContext]:
        with session_factory(TENANT_ID) as session:
            yield RequestContext(
                tenant_id=TENANT_ID,
                actor=admin.email,
                admin=admin,
                session=session,
            )

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_request_context] = request_context
    app.dependency_overrides[get_shopify_webhook_adapter_factory] = lambda: (
        failing_adapter_factory
    )
    app.dependency_overrides[get_shopify_webhook_dispatcher] = lambda: replay_dispatcher
    client = TestClient(app)
    body = b'{"id":42,"title":"retained for replay"}'
    headers = {
        "X-Shopify-Hmac-Sha256": _webhook_signature(body),
        "X-Shopify-Webhook-Id": "webhook-dead-letter",
        "X-Shopify-Shop-Domain": "merchant.myshopify.com",
        "X-Shopify-Topic": "products/update",
        "X-Shopify-API-Version": "2026-07",
    }

    failed = client.post(
        f"/api/v1/shopify/webhooks/ingress/{TENANT_ID}",
        content=body,
        headers=headers,
    )
    assert failed.status_code == 202
    assert failed.json()["status"] == "dead_letter"

    dead_letters = client.get("/api/v1/shopify/webhooks/dead-letters")
    assert dead_letters.status_code == 200
    assert len(dead_letters.json()) == 1
    dead_letter = dead_letters.json()[0]
    assert dead_letter["payload"] == {"id": 42, "title": "retained for replay"}
    assert "ConnectionError" in dead_letter["error_reason"]

    replay = client.post(f"/api/v1/shopify/webhooks/{dead_letter['event_id']}/replay")

    assert replay.status_code == 202
    assert replay.json()["status"] == "received"
    assert replay.json()["replay_count"] == 1
    assert replay_dispatcher.calls == [(UUID(dead_letter["event_id"]), TENANT_ID)]
    assert client.get("/api/v1/shopify/webhooks/dead-letters").json() == []
