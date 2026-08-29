"""Platform Adapter seam (Shopify write-back).

The generation stage must never write to Shopify.  The workflow orchestration
layer receives a :class:`PlatformAdapter` so that the publish and rollback
stages can act on the store.  Every write returns a :class:`PlatformReceipt`,
so the caller can prove the storefront accepted the change before marking any
local state as published — a failed receipt must never surface as a success.
"""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.domain.product import CanonicalProduct


@dataclass(frozen=True)
class PlatformReceipt:
    """Result of a storefront write.

    ``success`` is authoritative: local state may only move to ``published``
    when a storefront success receipt is returned.
    """

    success: bool
    remote_id: str | None = None
    error: str | None = None

    @classmethod
    def ok(cls, remote_id: str) -> "PlatformReceipt":
        return cls(success=True, remote_id=remote_id)

    @classmethod
    def failed(cls, error: str) -> "PlatformReceipt":
        return cls(success=False, error=error)


class PlatformAdapter(Protocol):
    """Write operations the AI platform can perform against a merchant store."""

    def publish_product(
        self, tenant_id: UUID, product: CanonicalProduct
    ) -> PlatformReceipt:
        """Create a new storefront product from a canonical product."""

    def update_product(
        self, tenant_id: UUID, product: CanonicalProduct
    ) -> PlatformReceipt:
        """Update an existing storefront product from a canonical product."""


@dataclass
class RecordingPlatformAdapter:
    """Fake Platform Adapter that records every write call.

    Used by seam A tests to assert the generation stage performs zero writes
    and to drive publish/rollback behaviour deterministically.
    """

    write_calls: list[tuple[str, UUID, CanonicalProduct]] = field(
        default_factory=list
    )
    receipts: list[PlatformReceipt] = field(default_factory=list)

    def publish_product(
        self, tenant_id: UUID, product: CanonicalProduct
    ) -> PlatformReceipt:
        self.write_calls.append(("publish_product", tenant_id, product))
        return self._next_receipt()

    def update_product(
        self, tenant_id: UUID, product: CanonicalProduct
    ) -> PlatformReceipt:
        self.write_calls.append(("update_product", tenant_id, product))
        return self._next_receipt()

    def _next_receipt(self) -> PlatformReceipt:
        if self.receipts:
            return self.receipts.pop(0)
        return PlatformReceipt.ok(remote_id=f"remote-{len(self.write_calls)}")


class NoopPlatformAdapter:
    """Platform Adapter used when no store is connected yet.

    Only the generation stage uses this default; publish and rollback always
    receive a store-backed adapter so they cannot silently no-op.
    """

    def publish_product(
        self, tenant_id: UUID, product: CanonicalProduct
    ) -> PlatformReceipt:
        del tenant_id, product
        return PlatformReceipt.ok(remote_id="noop")

    def update_product(
        self, tenant_id: UUID, product: CanonicalProduct
    ) -> PlatformReceipt:
        del tenant_id, product
        return PlatformReceipt.ok(remote_id="noop")
