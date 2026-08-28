import base64
import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from app.database import Base, TenantSession
from app.models import ShopifyStore, ShopifyWebhookEvent
from app.shopify.webhooks import (
    InvalidWebhookSignature,
    ShopifyWebhookAdapter,
    SqlAlchemyWebhookEvents,
    VerifiedWebhook,
    WebhookReceiptStatus,
    WebhookRegistration,
)

SHOPIFY_SECRET = "shopify-test-secret"
TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def _signature(body: bytes) -> str:
    digest = hmac.new(SHOPIFY_SECRET.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _headers(body: bytes, webhook_id: str = "webhook-123") -> dict[str, str]:
    return {
        "X-Shopify-Hmac-Sha256": _signature(body),
        "X-Shopify-Webhook-Id": webhook_id,
        "X-Shopify-Shop-Domain": "merchant.myshopify.com",
        "X-Shopify-Topic": "products/update",
        "X-Shopify-API-Version": "2026-07",
    }


@dataclass(frozen=True)
class StoredWebhook:
    event_id: UUID
    webhook: VerifiedWebhook


class InMemoryWebhookEvents:
    def __init__(self) -> None:
        self.by_webhook_id: dict[str, StoredWebhook] = {}
        self.dead_letters: dict[UUID, str] = {}

    def register(self, webhook: VerifiedWebhook) -> WebhookRegistration:
        existing = self.by_webhook_id.get(webhook.webhook_id)
        if existing is not None:
            return WebhookRegistration(event_id=existing.event_id, created=False)
        event_id = uuid4()
        self.by_webhook_id[webhook.webhook_id] = StoredWebhook(event_id, webhook)
        return WebhookRegistration(event_id=event_id, created=True)

    def mark_dead_letter(self, event_id: UUID, reason: str) -> None:
        self.dead_letters[event_id] = reason


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    def enqueue(self, event_id: UUID, tenant_id: UUID) -> None:
        self.calls.append((event_id, tenant_id))


def _adapter(
    events: InMemoryWebhookEvents, dispatcher: RecordingDispatcher
) -> ShopifyWebhookAdapter:
    return ShopifyWebhookAdapter(
        client_secret=SHOPIFY_SECRET,
        events=events,
        dispatcher=dispatcher,
    )


def test_webhook_rejects_invalid_hmac_before_storing_or_dispatching() -> None:
    events = InMemoryWebhookEvents()
    dispatcher = RecordingDispatcher()
    body = b'{"id": 42}'
    headers: Mapping[str, str] = {
        **_headers(body),
        "X-Shopify-Hmac-Sha256": "invalid",
    }

    with pytest.raises(InvalidWebhookSignature):
        _adapter(events, dispatcher).receive(
            tenant_id=TENANT_ID,
            body=body,
            headers=headers,
        )

    assert events.by_webhook_id == {}
    assert dispatcher.calls == []


def test_webhook_stores_raw_payload_and_dispatches_only_the_first_delivery() -> None:
    events = InMemoryWebhookEvents()
    dispatcher = RecordingDispatcher()
    adapter = _adapter(events, dispatcher)
    body = b'{"id":42,"title":"Original spacing is retained"}'
    headers = _headers(body)

    first = adapter.receive(tenant_id=TENANT_ID, body=body, headers=headers)
    duplicate = adapter.receive(tenant_id=TENANT_ID, body=body, headers=headers)

    assert first.status is WebhookReceiptStatus.ACCEPTED
    assert duplicate.status is WebhookReceiptStatus.DUPLICATE
    assert first.event_id == duplicate.event_id
    stored = events.by_webhook_id["webhook-123"]
    assert stored.webhook.raw_payload == body
    assert stored.webhook.payload == {
        "id": 42,
        "title": "Original spacing is retained",
    }
    assert dispatcher.calls == [(stored.event_id, TENANT_ID)]


def test_webhook_database_contract_enforces_idempotency_and_retains_payload() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def session_factory() -> TenantSession:
        return TenantSession(bind=engine, expire_on_commit=False, tenant_id=TENANT_ID)

    with session_factory() as session:
        session.add(
            ShopifyStore(
                tenant_id=TENANT_ID,
                shop_domain="merchant.myshopify.com",
                status="connected",
                encrypted_access_token=b"encrypted",
                access_token_nonce=b"nonce",
                granted_scopes=["write_products", "write_content"],
            )
        )
        session.commit()

    dispatcher = RecordingDispatcher()
    adapter = ShopifyWebhookAdapter(
        client_secret=SHOPIFY_SECRET,
        events=SqlAlchemyWebhookEvents(
            tenant_id=TENANT_ID,
            session_factory=session_factory,
        ),
        dispatcher=dispatcher,
    )
    body = b'{"id":42,"title":"payload survives failures"}'

    first = adapter.receive(tenant_id=TENANT_ID, body=body, headers=_headers(body))
    second = adapter.receive(tenant_id=TENANT_ID, body=body, headers=_headers(body))

    assert first.event_id == second.event_id
    with session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(ShopifyWebhookEvent)) == 1
        )
        event = session.scalar(select(ShopifyWebhookEvent))
        assert event is not None
        assert event.raw_payload == body
        assert event.payload == {"id": 42, "title": "payload survives failures"}
