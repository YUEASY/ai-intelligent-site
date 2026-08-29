from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProductStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class CanonicalVariant(BaseModel):
    """Source-independent variant in the 商品标准模型."""

    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=255)
    options: dict[str, str]
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    cost: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    inventory: int = Field(ge=0, le=2_147_483_647)
    image: str | None = Field(default=None, max_length=2048)


class CanonicalProduct(BaseModel):
    """Source-independent normalized product consumed by business services."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    source: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)
    sku: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    description: str
    category: str
    tags: list[str]
    images: list[str]
    meta_title: str = Field(max_length=255)
    meta_description: str
    handle: str = Field(min_length=1, max_length=255)
    status: ProductStatus
    shopify_product_id: str | None = None
    variants: list[CanonicalVariant] = Field(min_length=1)


def ensure_supported_option_count(product: CanonicalProduct) -> None:
    for variant in product.variants:
        if len(variant.options) > 2:
            raise ValueError(
                f"Variant {variant.sku} supports at most 2 option dimensions"
            )
