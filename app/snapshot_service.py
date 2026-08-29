"""Version snapshots: capture, list, and restore product state."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.database import TenantSession
from app.domain.snapshot import SnapshotKind, diff_states
from app.models import Product, ProductSnapshot


class SnapshotNotFoundError(LookupError):
    pass


class SnapshotService:
    """Persist and read versioned snapshots for a product."""

    def __init__(self, session: TenantSession) -> None:
        self._session = session

    def capture(
        self,
        product: Product,
        *,
        before: dict[str, Any],
        after: dict[str, Any],
        actor: str,
        kind: SnapshotKind,
        restored_version: int | None = None,
    ) -> ProductSnapshot:
        """Record the pre-change state (``before``) and the upcoming diff."""
        latest = self.latest(product.id)
        version = (latest.version + 1) if latest else 1
        snapshot = ProductSnapshot(
            tenant_id=self._session.tenant_id,
            product_id=product.id,
            version=version,
            kind=kind.value,
            payload=before,
            field_diff=diff_states(before, after),
            actor=actor,
            restored_version=restored_version,
        )
        self._session.add(snapshot)
        self._session.flush()
        return snapshot

    def list_versions(self, product_id: UUID) -> list[ProductSnapshot]:
        statement = (
            select(ProductSnapshot)
            .where(ProductSnapshot.product_id == product_id)
            .order_by(ProductSnapshot.version.desc())
        )
        return list(self._session.scalars(statement))

    def get(self, product_id: UUID, version: int) -> ProductSnapshot:
        snapshot = self._session.scalar(
            select(ProductSnapshot).where(
                ProductSnapshot.product_id == product_id,
                ProductSnapshot.version == version,
            )
        )
        if snapshot is None:
            raise SnapshotNotFoundError(str(version))
        return snapshot

    def latest(self, product_id: UUID) -> ProductSnapshot | None:
        return self._session.scalar(
            select(ProductSnapshot)
            .where(ProductSnapshot.product_id == product_id)
            .order_by(ProductSnapshot.version.desc())
            .limit(1)
        )


def apply_state_to_product(product: Product, state: dict[str, Any]) -> None:
    """Restore a product's columns and variants from a serialized state."""
    product.title = state["title"]
    product.description = state["description"]
    product.category = state["category"]
    product.tags = list(state["tags"])
    product.images = list(state["images"])
    product.meta_title = state["meta_title"]
    product.meta_description = state["meta_description"]
    product.alt_text = dict(state.get("alt_text", {}))
    product.handle = state["handle"]
    product.status = state["status"]

    variants_by_sku = {variant.sku: variant for variant in product.variants}
    for variant_state in state["variants"]:
        variant = variants_by_sku.get(variant_state["sku"])
        if variant is None:
            continue
        variant.options = dict(variant_state["options"])
        variant.price = Decimal(variant_state["price"])
        variant.cost = (
            Decimal(variant_state["cost"])
            if variant_state["cost"] is not None
            else None
        )
        variant.inventory = int(variant_state["inventory"])
        variant.image = variant_state["image"]
