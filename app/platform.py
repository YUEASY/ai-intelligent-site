"""Platform Adapter seam (Shopify write-back).

The generation stage must never write to Shopify.  The workflow orchestration
layer receives a :class:`PlatformAdapter` so that future stages (publish) can
act on the store, while the generation stage provably ignores it.
"""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.domain.product import CanonicalProduct


class PlatformAdapter(Protocol):
    """Write operations the AI platform can perform against a merchant store."""

    def publish_product(self, tenant_id: UUID, product: CanonicalProduct) -> None:
        """Publish a canonical product to the merchant's storefront."""

    def update_product(self, tenant_id: UUID, product: CanonicalProduct) -> None:
        """Update an existing storefront product from a canonical product."""


@dataclass
class RecordingPlatformAdapter:
    """Fake Platform Adapter that records every write call.

    Used by seam A tests to assert the generation stage performs zero writes.
    """

    write_calls: list[tuple[str, UUID, CanonicalProduct]] = field(
        default_factory=list
    )

    def publish_product(self, tenant_id: UUID, product: CanonicalProduct) -> None:
        self.write_calls.append(("publish_product", tenant_id, product))

    def update_product(self, tenant_id: UUID, product: CanonicalProduct) -> None:
        self.write_calls.append(("update_product", tenant_id, product))


class NoopPlatformAdapter:
    """Platform Adapter used when no store is connected yet."""

    def publish_product(self, tenant_id: UUID, product: CanonicalProduct) -> None:
        del tenant_id, product

    def update_product(self, tenant_id: UUID, product: CanonicalProduct) -> None:
        del tenant_id, product
