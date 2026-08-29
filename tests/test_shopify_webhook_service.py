from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from app.database import Base, TenantSession
from app.domain.alert import AlertKind
from app.models import Alert, ShopifyStore, ShopifyWebhookEvent
from app.shopify.types import ShopifyStoreStatus, WebhookEventStatus
from app.shopify.webhook_service import ShopifyWebhookService, WebhookEventNotFound

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
SHOP_DOMAIN = "merchant.myshopify.com"


@pytest.fixture()
def session_factory() -> Callable[[], TenantSession]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def factory() -> TenantSession:
        return TenantSession(bind=engine, expire_on_commit=False, tenant_id=TENANT_ID)

    return factory


def _create_connected_store(session_factory: Callable[[], TenantSession]) -> UUID:
    with session_factory() as session:
        store = ShopifyStore(
            tenant_id=TENANT_ID,
            shop_domain=SHOP_DOMAIN,
            status=ShopifyStoreStatus.CONNECTED.value,
            encrypted_access_token=b"ciphertext",
            access_token_nonce=b"nonce",
            granted_scopes=["write_products", "write_content"],
        )
        session.add(store)
        session.commit()
        return store.id


def _create_event(
    session_factory: Callable[[], TenantSession],
    store_id: UUID,
    topic: str,
    status: WebhookEventStatus,
) -> UUID:
    with session_factory() as session:
        event = ShopifyWebhookEvent(
            tenant_id=TENANT_ID,
            store_id=store_id,
            webhook_id=f"webhook-{uuid4()}",
            shop_domain=SHOP_DOMAIN,
            topic=topic,
            api_version="2026-07",
            raw_payload=b"{}",
            payload={},
            status=status.value,
        )
        session.add(event)
        session.commit()
        return event.id


def test_uninstall_webhook_disconnects_store_and_clears_token(
    session_factory: Callable[[], TenantSession],
) -> None:
    store_id = _create_connected_store(session_factory)
    event_id = _create_event(
        session_factory,
        store_id,
        "app/uninstalled",
        WebhookEventStatus.RECEIVED,
    )

    with session_factory() as session:
        result = ShopifyWebhookService(session).process(event_id)
        session.commit()

    assert result == WebhookEventStatus.PROCESSED.value
    with session_factory() as session:
        store = session.scalar(select(ShopifyStore).where(ShopifyStore.id == store_id))
        assert store is not None
        assert store.status == ShopifyStoreStatus.DISCONNECTED.value
        assert store.encrypted_access_token is None
        assert store.access_token_nonce is None
        assert store.disconnected_at is not None
        event = session.scalar(
            select(ShopifyWebhookEvent).where(ShopifyWebhookEvent.id == event_id)
        )
        assert event is not None
        assert event.status == WebhookEventStatus.PROCESSED.value
        assert event.processed_at is not None


def test_non_uninstall_webhook_keeps_store_connected(
    session_factory: Callable[[], TenantSession],
) -> None:
    store_id = _create_connected_store(session_factory)
    event_id = _create_event(
        session_factory,
        store_id,
        "products/update",
        WebhookEventStatus.RECEIVED,
    )

    with session_factory() as session:
        ShopifyWebhookService(session).process(event_id)
        session.commit()

    with session_factory() as session:
        store = session.scalar(select(ShopifyStore).where(ShopifyStore.id == store_id))
        assert store is not None
        assert store.status == ShopifyStoreStatus.CONNECTED.value
        assert store.encrypted_access_token == b"ciphertext"


def test_processing_an_already_processed_event_does_not_touch_the_store(
    session_factory: Callable[[], TenantSession],
) -> None:
    store_id = _create_connected_store(session_factory)
    event_id = _create_event(
        session_factory,
        store_id,
        "app/uninstalled",
        WebhookEventStatus.PROCESSED,
    )

    with session_factory() as session:
        result = ShopifyWebhookService(session).process(event_id)

    assert result == WebhookEventStatus.PROCESSED.value
    with session_factory() as session:
        store = session.scalar(select(ShopifyStore).where(ShopifyStore.id == store_id))
        assert store is not None
        assert store.status == ShopifyStoreStatus.CONNECTED.value
        assert store.encrypted_access_token == b"ciphertext"


def test_processing_unknown_event_raises(
    session_factory: Callable[[], TenantSession],
) -> None:
    with session_factory() as session, pytest.raises(WebhookEventNotFound):
        ShopifyWebhookService(session).process(uuid4())


def test_mark_dead_letter_raises_a_dead_letter_alert(
    session_factory: Callable[[], TenantSession],
) -> None:
    store_id = _create_connected_store(session_factory)
    event_id = _create_event(
        session_factory,
        store_id,
        "products/update",
        WebhookEventStatus.RECEIVED,
    )

    with session_factory() as session:
        ShopifyWebhookService(session).mark_dead_letter(event_id, "boom")
        session.commit()

    with session_factory() as session:
        alert = session.scalar(
            select(Alert).where(Alert.kind == AlertKind.DEAD_LETTER.value)
        )
        assert alert is not None
        assert str(event_id) in alert.message
        assert alert.dedup_key == f"webhook:{event_id}"
