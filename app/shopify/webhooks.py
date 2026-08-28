import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import TenantSession
from app.models import ShopifyStore, ShopifyWebhookEvent


class InvalidWebhookSignature(ValueError):
    pass


class InvalidWebhookRequest(ValueError):
    pass


class WebhookDispatchFailed(RuntimeError):
    def __init__(self, event_id: UUID, reason: str) -> None:
        super().__init__(reason)
        self.event_id = event_id


class UnknownShopifyStore(LookupError):
    pass


@dataclass(frozen=True)
class VerifiedWebhook:
    tenant_id: UUID
    webhook_id: str
    shop_domain: str
    topic: str
    api_version: str
    raw_payload: bytes
    payload: dict[str, object]


@dataclass(frozen=True)
class WebhookRegistration:
    event_id: UUID
    created: bool


class WebhookReceiptStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class WebhookReceipt:
    event_id: UUID
    status: WebhookReceiptStatus


class WebhookEvents(Protocol):
    def register(self, webhook: VerifiedWebhook) -> WebhookRegistration: ...

    def mark_dead_letter(self, event_id: UUID, reason: str) -> None: ...


class WebhookDispatcher(Protocol):
    def enqueue(self, event_id: UUID, tenant_id: UUID) -> None: ...


class SqlAlchemyWebhookEvents:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        session_factory: "CallableSessionFactory",
    ) -> None:
        self._tenant_id = tenant_id
        self._session_factory = session_factory

    def register(self, webhook: VerifiedWebhook) -> WebhookRegistration:
        if webhook.tenant_id != self._tenant_id:
            raise ValueError("Webhook tenant does not match repository tenant")

        event_id = uuid4()
        with self._session_factory() as session:
            store = session.scalar(
                select(ShopifyStore).where(
                    ShopifyStore.shop_domain == webhook.shop_domain,
                    ShopifyStore.status == "connected",
                )
            )
            if store is None:
                raise UnknownShopifyStore(webhook.shop_domain)
            session.add(
                ShopifyWebhookEvent(
                    id=event_id,
                    tenant_id=self._tenant_id,
                    store_id=store.id,
                    webhook_id=webhook.webhook_id,
                    shop_domain=webhook.shop_domain,
                    topic=webhook.topic,
                    api_version=webhook.api_version,
                    raw_payload=webhook.raw_payload,
                    payload=webhook.payload,
                    status="received",
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing_id = session.scalar(
                    select(ShopifyWebhookEvent.id).where(
                        ShopifyWebhookEvent.webhook_id == webhook.webhook_id
                    )
                )
                if existing_id is None:
                    raise
                return WebhookRegistration(event_id=existing_id, created=False)
        return WebhookRegistration(event_id=event_id, created=True)

    def mark_dead_letter(self, event_id: UUID, reason: str) -> None:
        with self._session_factory() as session:
            event = session.scalar(
                select(ShopifyWebhookEvent).where(ShopifyWebhookEvent.id == event_id)
            )
            if event is None:
                return
            event.status = "dead_letter"
            event.error_reason = reason
            session.commit()


class CallableSessionFactory(Protocol):
    def __call__(self) -> TenantSession: ...


class ShopifyWebhookAdapter:
    def __init__(
        self,
        *,
        client_secret: str,
        events: WebhookEvents,
        dispatcher: WebhookDispatcher,
    ) -> None:
        self._client_secret = client_secret.encode()
        self._events = events
        self._dispatcher = dispatcher

    def receive(
        self,
        *,
        tenant_id: UUID,
        body: bytes,
        headers: Mapping[str, str],
    ) -> WebhookReceipt:
        normalized_headers = {name.lower(): value for name, value in headers.items()}
        self._verify_hmac(body, normalized_headers.get("x-shopify-hmac-sha256"))

        webhook = VerifiedWebhook(
            tenant_id=tenant_id,
            webhook_id=self._required_header(
                normalized_headers, "x-shopify-webhook-id"
            ),
            shop_domain=self._required_header(
                normalized_headers, "x-shopify-shop-domain"
            ),
            topic=self._required_header(normalized_headers, "x-shopify-topic"),
            api_version=self._required_header(
                normalized_headers, "x-shopify-api-version"
            ),
            raw_payload=body,
            payload=self._parse_payload(body),
        )
        registration = self._events.register(webhook)
        if not registration.created:
            return WebhookReceipt(
                event_id=registration.event_id,
                status=WebhookReceiptStatus.DUPLICATE,
            )

        try:
            self._dispatcher.enqueue(registration.event_id, tenant_id)
        except Exception as exc:
            reason = f"Webhook dispatch failed: {type(exc).__name__}"
            self._events.mark_dead_letter(registration.event_id, reason)
            raise WebhookDispatchFailed(registration.event_id, reason) from exc

        return WebhookReceipt(
            event_id=registration.event_id,
            status=WebhookReceiptStatus.ACCEPTED,
        )

    def _verify_hmac(self, body: bytes, supplied_hmac: str | None) -> None:
        expected = base64.b64encode(
            hmac.new(self._client_secret, body, hashlib.sha256).digest()
        ).decode()
        if supplied_hmac is None or not hmac.compare_digest(expected, supplied_hmac):
            raise InvalidWebhookSignature("Invalid Shopify webhook HMAC")

    @staticmethod
    def _required_header(headers: Mapping[str, str], name: str) -> str:
        value = headers.get(name)
        if not value:
            raise InvalidWebhookRequest(f"Missing required header: {name}")
        return value

    @staticmethod
    def _parse_payload(body: bytes) -> dict[str, object]:
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidWebhookRequest("Webhook payload must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise InvalidWebhookRequest("Webhook payload must be a JSON object")
        return payload
