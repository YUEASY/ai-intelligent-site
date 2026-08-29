from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import TenantScopeViolation, TenantSession
from app.importing.csv_adapter import CanonicalProduct
from app.models import Product, ProductVariant


class ProductImportConflict(ValueError):
    pass


class ProductService:
    def __init__(self, session: TenantSession) -> None:
        self._session = session

    def import_products(self, products: list[CanonicalProduct]) -> list[Product]:
        self._ensure_import_is_unique(products)
        records: list[Product] = []
        for canonical in products:
            if canonical.tenant_id != self._session.tenant_id:
                raise TenantScopeViolation(
                    "Canonical product does not belong to the current tenant"
                )
            record = Product(
                tenant_id=canonical.tenant_id,
                source=canonical.source,
                source_id=canonical.source_id,
                sku=canonical.sku,
                title=canonical.title,
                description=canonical.description,
                category=canonical.category,
                tags=canonical.tags,
                images=canonical.images,
                meta_title=canonical.meta_title,
                meta_description=canonical.meta_description,
                handle=canonical.handle,
                status=canonical.status,
                variants=[
                    ProductVariant(
                        tenant_id=canonical.tenant_id,
                        sku=variant.sku,
                        options=variant.options,
                        price=variant.price,
                        cost=variant.cost,
                        inventory=variant.inventory,
                        image=variant.image,
                    )
                    for variant in canonical.variants
                ],
            )
            self._session.add(record)
            records.append(record)
        self._session.flush()
        return records

    def _ensure_import_is_unique(self, products: list[CanonicalProduct]) -> None:
        product_skus: set[str] = set()
        handles: set[str] = set()
        variant_skus: set[str] = set()
        for canonical in products:
            existing_source = self._session.scalar(
                select(Product).where(
                    Product.source == canonical.source,
                    Product.source_id == canonical.source_id,
                )
            )
            if existing_source is not None:
                raise ProductImportConflict(
                    f"Product {canonical.source}/{canonical.source_id} "
                    "already exists for this tenant"
                )

            if canonical.sku in product_skus or self._session.scalar(
                select(Product.id).where(Product.sku == canonical.sku)
            ):
                raise ProductImportConflict(
                    f"Product SKU {canonical.sku} already exists for this tenant"
                )
            if canonical.handle in handles or self._session.scalar(
                select(Product.id).where(Product.handle == canonical.handle)
            ):
                raise ProductImportConflict(
                    f"Product handle {canonical.handle} already exists for this tenant"
                )

            product_skus.add(canonical.sku)
            handles.add(canonical.handle)
            for variant in canonical.variants:
                if variant.sku in variant_skus or self._session.scalar(
                    select(ProductVariant.id).where(ProductVariant.sku == variant.sku)
                ):
                    raise ProductImportConflict(
                        f"Variant SKU {variant.sku} already exists for this tenant"
                    )
                variant_skus.add(variant.sku)

    def list_products(self) -> list[Product]:
        statement = (
            select(Product)
            .options(selectinload(Product.variants))
            .order_by(Product.created_at, Product.id)
        )
        return list(self._session.scalars(statement))
