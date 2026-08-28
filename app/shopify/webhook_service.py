from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.database import TenantSession
from app.models import ShopifyStore, ShopifyWebhookEvent


class WebhookEventNotFound(LookupError):
    pass


class InvalidWebhookReplay(ValueError):
    pass


class ShopifyWebhookService:
    def __init__(self, session: TenantSession) -> None:
        self._session = session

    def list_dead_letters(self) -> list[ShopifyWebhookEvent]:
        statement = (
            select(ShopifyWebhookEvent)
            .where(ShopifyWebhookEvent.status == "dead_letter")
            .order_by(ShopifyWebhookEvent.received_at, ShopifyWebhookEvent.id)
        )
        return list(self._session.scalars(statement))

    def replay(self, event_id: UUID) -> ShopifyWebhookEvent:
        event = self._get(event_id, for_update=True)
        if event.status != "dead_letter":
            raise InvalidWebhookReplay("Only dead-letter events can be replayed")
        event.status = "received"
        event.error_reason = None
        event.processed_at = None
        event.replay_count += 1
        self._session.flush()
        return event

    def process(self, event_id: UUID) -> str:
        event = self._get(event_id, for_update=True)
        if event.status != "received":
            return event.status

        if event.topic == "app/uninstalled":
            store = self._session.scalar(
                select(ShopifyStore)
                .where(ShopifyStore.id == event.store_id)
                .with_for_update()
            )
            if store is not None:
                store.status = "disconnected"
                store.encrypted_access_token = None
                store.access_token_nonce = None
                store.disconnected_at = datetime.now(UTC)

        event.status = "processed"
        event.processed_at = datetime.now(UTC)
        event.error_reason = None
        self._session.flush()
        return event.status

    def mark_dead_letter(self, event_id: UUID, reason: str) -> None:
        event = self._get(event_id, for_update=True)
        event.status = "dead_letter"
        event.error_reason = reason[:2000]
        event.processed_at = None
        self._session.flush()

    def _get(self, event_id: UUID, *, for_update: bool = False) -> ShopifyWebhookEvent:
        statement = select(ShopifyWebhookEvent).where(
            ShopifyWebhookEvent.id == event_id
        )
        if for_update:
            statement = statement.with_for_update()
        event = self._session.scalar(statement)
        if event is None:
            raise WebhookEventNotFound(str(event_id))
        return event
