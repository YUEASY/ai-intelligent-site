"""Publish and rollback orchestration over the Platform Adapter seam.

Publishing is a high-risk operation: it writes to the storefront, so it always
requires human confirmation, and local state only moves to ``published`` after
the adapter returns a success receipt.  Both publish and rollback record a
version snapshot with a field-level diff, so the storefront can be restored to
any earlier version.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.database import TenantSession
from app.domain.draft import DraftStatus
from app.domain.product import (
    CanonicalProduct,
    CanonicalVariant,
    ProductStatus,
)
from app.domain.snapshot import SnapshotKind, apply_draft_to_state, product_state
from app.domain.task_state import TaskState
from app.generation.service import DraftNotFoundError
from app.models import Product, ProductDraft, ProductSnapshot, Task
from app.platform import PlatformAdapter, PlatformReceipt
from app.product_service import ProductService
from app.services import TaskService
from app.snapshot_service import SnapshotService, apply_state_to_product


class PublishConfirmationRequired(ValueError):
    pass


class DraftNotPublishable(ValueError):
    pass


class PublishFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishResult:
    draft: ProductDraft
    task: Task
    snapshot: ProductSnapshot
    remote_id: str


@dataclass(frozen=True)
class RollbackResult:
    product: Product
    task: Task | None
    snapshot: ProductSnapshot


@dataclass(frozen=True)
class ProductWriteResult:
    snapshot: ProductSnapshot
    receipt: PlatformReceipt


def canonical_from_state(product: Product, state: dict[str, Any]) -> CanonicalProduct:
    """Rebuild a canonical product from a serialized product state."""
    return CanonicalProduct(
        tenant_id=product.tenant_id,
        source=product.source,
        source_id=product.source_id,
        sku=product.sku,
        title=state["title"],
        description=state["description"],
        category=state["category"],
        tags=list(state["tags"]),
        images=list(state["images"]),
        meta_title=state["meta_title"],
        meta_description=state["meta_description"],
        alt_text=dict(state.get("alt_text", {})),
        handle=state["handle"],
        status=ProductStatus(state["status"]),
        shopify_product_id=product.shopify_product_id,
        variants=[
            CanonicalVariant(
                sku=variant["sku"],
                options=dict(variant["options"]),
                price=Decimal(variant["price"]),
                cost=(
                    Decimal(variant["cost"]) if variant["cost"] is not None else None
                ),
                inventory=int(variant["inventory"]),
                image=variant["image"],
            )
            for variant in state["variants"]
        ],
    )


def write_product_state(
    session: TenantSession,
    actor: str,
    adapter: PlatformAdapter,
    product: Product,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    kind: SnapshotKind = SnapshotKind.PUBLISH,
    restored_version: int | None = None,
) -> ProductWriteResult:
    """Capture a snapshot, write the storefront, then apply confirmed state."""
    snapshot = SnapshotService(session).capture(
        product,
        before=before,
        after=after,
        actor=actor,
        kind=kind,
        restored_version=restored_version,
    )
    canonical = canonical_from_state(product, after)
    receipt = (
        adapter.publish_product(session.tenant_id, canonical)
        if product.shopify_product_id is None
        else adapter.update_product(session.tenant_id, canonical)
    )
    if not receipt.success:
        session.delete(snapshot)
        return ProductWriteResult(snapshot, receipt)
    apply_state_to_product(product, after)
    if receipt.remote_id:
        product.shopify_product_id = receipt.remote_id
    return ProductWriteResult(snapshot, receipt)


class PublishService:
    def __init__(
        self, session: TenantSession, actor: str, adapter: PlatformAdapter
    ) -> None:
        self._session = session
        self._actor = actor
        self._adapter = adapter

    def publish(self, draft_id: UUID, *, confirmed: bool) -> PublishResult:
        if not confirmed:
            raise PublishConfirmationRequired(
                "Publishing is high-risk and requires explicit confirmation"
            )
        draft = self._get_draft(draft_id)
        if draft.status != DraftStatus.APPROVED.value:
            raise DraftNotPublishable(f"Draft {draft_id} cannot be published")

        product = ProductService(self._session).get(draft.product_id)
        task_service = TaskService(self._session, self._actor)
        task = task_service.get(draft.task_id, for_update=True)

        before = product_state(product)
        after = apply_draft_to_state(before, draft)
        after["status"] = ProductStatus.ACTIVE.value
        write = write_product_state(
            self._session, self._actor, self._adapter, product, before, after
        )
        snapshot, receipt = write.snapshot, write.receipt
        if not receipt.success:
            raise PublishFailed(receipt.error or "Shopify did not confirm the publish")
        product.status = ProductStatus.ACTIVE.value

        task_service.advance(draft.task_id, TaskState.PUBLISHED)
        draft.status = DraftStatus.PUBLISHED.value
        self._session.flush()
        return PublishResult(
            draft=draft,
            task=task,
            snapshot=snapshot,
            remote_id=receipt.remote_id or "",
        )

    def rollback(self, product_id: UUID, version: int) -> RollbackResult:
        product = ProductService(self._session).get(product_id)
        snapshots = SnapshotService(self._session)
        target = snapshots.get(product_id, version)

        before = product_state(product)
        after = dict(target.payload)
        write = write_product_state(
            self._session,
            self._actor,
            self._adapter,
            product,
            before,
            after,
            kind=SnapshotKind.ROLLBACK,
            restored_version=version,
        )
        snapshot, receipt = write.snapshot, write.receipt
        if not receipt.success:
            raise PublishFailed(receipt.error or "Shopify did not confirm the rollback")

        task = self._latest_published_task(product_id)
        if task is not None:
            TaskService(self._session, self._actor).advance(
                task.id, TaskState.ROLLED_BACK
            )
            self._mark_draft_rolled_back(task.id)

        self._session.flush()
        return RollbackResult(product=product, task=task, snapshot=snapshot)

    def _get_draft(self, draft_id: UUID) -> ProductDraft:
        draft = self._session.scalar(
            select(ProductDraft).where(ProductDraft.id == draft_id)
        )
        if draft is None:
            raise DraftNotFoundError(str(draft_id))
        return draft

    def _latest_published_task(self, product_id: UUID) -> Task | None:
        return self._session.scalar(
            select(Task)
            .where(
                Task.product_id == product_id,
                Task.status == TaskState.PUBLISHED.value,
            )
            .order_by(Task.updated_at.desc())
            .limit(1)
        )

    def _mark_draft_rolled_back(self, task_id: UUID) -> None:
        draft = self._session.scalar(
            select(ProductDraft).where(
                ProductDraft.task_id == task_id,
                ProductDraft.status == DraftStatus.PUBLISHED.value,
            )
        )
        if draft is not None:
            draft.status = DraftStatus.ROLLED_BACK.value
