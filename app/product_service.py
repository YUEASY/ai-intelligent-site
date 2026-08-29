import hashlib
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import TenantScopeViolation, TenantSession
from app.domain.product import CanonicalProduct, ensure_supported_option_count
from app.models import Product, ProductImageAsset, ProductVariant

MAX_IMAGE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class ProductImageUpload:
    filename: str
    content_type: str
    content: bytes


class ProductImportValidationError(ValueError):
    pass


class ProductImportConflict(ValueError):
    pass


class ProductImageNotFoundError(LookupError):
    pass


class ProductService:
    def __init__(self, session: TenantSession) -> None:
        self._session = session

    def import_products(
        self,
        products: list[CanonicalProduct],
        image_uploads: list[ProductImageUpload] | None = None,
    ) -> list[Product]:
        for product in products:
            try:
                ensure_supported_option_count(product)
            except ValueError as exc:
                raise ProductImportValidationError(str(exc)) from exc
        uploads_by_name = self._validate_images(image_uploads or [])
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
                image_assets=self._image_assets(canonical, uploads_by_name),
            )
            self._session.add(record)
            records.append(record)
        self._session.flush()
        return records

    def _validate_images(
        self, uploads: list[ProductImageUpload]
    ) -> dict[str, ProductImageUpload]:
        uploads_by_name: dict[str, ProductImageUpload] = {}
        for upload in uploads:
            if not upload.filename:
                raise ProductImportValidationError("Uploaded images need a filename")
            if len(upload.filename) > 255:
                raise ProductImportValidationError(
                    f"Image filename {upload.filename} exceeds 255 characters"
                )
            if upload.filename in uploads_by_name:
                raise ProductImportValidationError(
                    f"Image {upload.filename} was uploaded more than once"
                )
            if not upload.content:
                raise ProductImportValidationError(
                    f"Image {upload.filename} must not be empty"
                )
            if not upload.content_type.lower().startswith("image/"):
                raise ProductImportValidationError(
                    f"File {upload.filename} is not an image"
                )
            if len(upload.content) > MAX_IMAGE_BYTES:
                raise ProductImportValidationError(
                    f"Image {upload.filename} exceeds the 10 MB limit"
                )
            uploads_by_name[upload.filename] = upload
        return uploads_by_name

    def _image_assets(
        self,
        product: CanonicalProduct,
        uploads_by_name: dict[str, ProductImageUpload],
    ) -> list[ProductImageAsset]:
        references = dict.fromkeys(
            [*product.images, *(v.image for v in product.variants if v.image)]
        )
        local_references = [ref for ref in references if not _is_remote_image(ref)]
        missing = [ref for ref in local_references if ref not in uploads_by_name]
        if missing:
            raise ProductImportValidationError(
                "Missing uploaded images: " + ", ".join(missing)
            )
        return [
            ProductImageAsset(
                tenant_id=product.tenant_id,
                filename=reference,
                content_type=uploads_by_name[reference].content_type,
                content=uploads_by_name[reference].content,
                sha256=hashlib.sha256(uploads_by_name[reference].content).hexdigest(),
            )
            for reference in local_references
        ]

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

    def get_image(self, product_id: UUID, filename: str) -> ProductImageAsset:
        image = self._session.scalar(
            select(ProductImageAsset).where(
                ProductImageAsset.product_id == product_id,
                ProductImageAsset.filename == filename,
            )
        )
        if image is None:
            raise ProductImageNotFoundError(filename)
        return image


def _is_remote_image(reference: str) -> bool:
    parsed = urlparse(reference)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
