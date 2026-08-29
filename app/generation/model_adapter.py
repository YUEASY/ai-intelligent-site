"""Model Adapter seam.

The Model Adapter is the only place that may talk to a language model.  The
rest of the codebase depends on its structured I/O contract rather than on
prompt text, so a fake adapter can stand in for the real one in tests.

Routing is deterministic: pure-code checks never call a model, meta/alt/short
title go to the small model, and detail copy goes to the large model.
"""

import re
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from app.domain.product import CanonicalProduct
from app.domain.risk import ProductField

PRICE_PATTERN = re.compile(
    r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\b\d+\.\d{2}\b"
)

# Detail copy needs the large model; everything else the MVP generates is a
# short, low-latency field that the small model can produce reliably.
LARGE_MODEL_FIELDS = frozenset({ProductField.DESCRIPTION})
SMALL_MODEL_FIELDS = frozenset(
    {
        ProductField.TITLE,
        ProductField.META_TITLE,
        ProductField.META_DESCRIPTION,
        ProductField.ALT_TEXT,
        ProductField.SEO_TAGS,
    }
)


class ModelTier(StrEnum):
    SMALL = "small"
    LARGE = "large"


class GeneratedContent(BaseModel):
    """Structured output contract for generated product content.

    Deliberately contains only content fields: SKU / price / inventory /
    material / size are factual fields that generation must never invent, so
    they are absent from this schema by construction.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    alt_text: dict[str, str] | None = None
    seo_tags: list[str] | None = None


class ModelAdapter(Protocol):
    """Generate content for a single model tier using only real product data."""

    def generate(
        self,
        tier: ModelTier,
        product: CanonicalProduct,
        fields: frozenset[ProductField],
    ) -> GeneratedContent:
        """Return a partial :class:`GeneratedContent` for exactly `fields`."""


class FactViolation(BaseModel):
    message: str


def model_tier_for_field(field: ProductField) -> ModelTier:
    if field in LARGE_MODEL_FIELDS:
        return ModelTier.LARGE
    if field in SMALL_MODEL_FIELDS:
        return ModelTier.SMALL
    raise ValueError(f"No model tier routes field {field.value}")


def group_fields_by_tier(
    fields: frozenset[ProductField],
) -> dict[ModelTier, frozenset[ProductField]]:
    grouped: dict[ModelTier, set[ProductField]] = {}
    for field in fields:
        grouped.setdefault(model_tier_for_field(field), set()).add(field)
    return {tier: frozenset(items) for tier, items in grouped.items()}


def _alt_texts(product: CanonicalProduct) -> dict[str, str]:
    return {
        image: f"{product.title} {product.category}".strip()
        for image in product.images
    }


def _seo_tags(product: CanonicalProduct) -> list[str]:
    return sorted({*product.tags, product.category})


class DeterministicModelAdapter:
    """Fact-safe stand-in for the LLM used in development and tests.

    It never calls a model and derives every field from the product's own real
    data, so the factual fields it references are correct by construction.
    """

    def generate(
        self,
        tier: ModelTier,
        product: CanonicalProduct,
        fields: frozenset[ProductField],
    ) -> GeneratedContent:
        del tier
        content = GeneratedContent()
        if ProductField.TITLE in fields:
            content.title = product.title
        if ProductField.DESCRIPTION in fields:
            content.description = product.description
        if ProductField.META_TITLE in fields:
            content.meta_title = product.meta_title or product.title
        if ProductField.META_DESCRIPTION in fields:
            content.meta_description = product.meta_description or product.description
        if ProductField.ALT_TEXT in fields:
            content.alt_text = _alt_texts(product)
        if ProductField.SEO_TAGS in fields:
            content.seo_tags = _seo_tags(product)
        return content


def check_facts(
    content: GeneratedContent, product: CanonicalProduct
) -> list[FactViolation]:
    """Deterministic guard: generated copy must not fabricate a price.

    SKU / material / size are factual fields absent from the generated-content
    schema, so they cannot be altered by the generation stage.  Prices can leak
    into descriptive copy, so any monetary amount that does not match a real
    variant price or cost is a violation.
    """
    real_amounts = _real_amounts(product)
    text = " ".join(
        part
        for part in (
            content.title,
            content.description,
            content.meta_title,
            content.meta_description,
            *(content.seo_tags or []),
            *(content.alt_text or {}).values(),
        )
        if part
    )
    violations: list[FactViolation] = []
    for match in PRICE_PATTERN.finditer(text):
        token = match.group(0)
        amount = _parse_amount(token)
        if amount is None:
            continue
        if amount not in real_amounts:
            violations.append(
                FactViolation(
                    message=f"generated content mentions price {token} "
                    "not present in product data"
                )
            )
    return violations


def _real_amounts(product: CanonicalProduct) -> set[Decimal]:
    amounts: set[Decimal] = set()
    for variant in product.variants:
        amounts.add(variant.price)
        if variant.cost is not None:
            amounts.add(variant.cost)
    return amounts


def _parse_amount(token: str) -> Decimal | None:
    cleaned = token.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None
