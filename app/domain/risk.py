from collections.abc import Collection
from enum import StrEnum


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OperationType(StrEnum):
    UPDATE = "update"
    PUBLISH = "publish"
    REFUND = "refund"


class ProductField(StrEnum):
    META_TITLE = "meta_title"
    META_DESCRIPTION = "meta_description"
    ALT_TEXT = "alt_text"
    SEO_TAGS = "seo_tags"
    TITLE = "title"
    DESCRIPTION = "description"
    PRICE = "price"
    INVENTORY = "inventory"


class InvalidRiskInput(ValueError):
    pass


LOW_RISK_FIELDS = frozenset(
    {
        ProductField.META_TITLE,
        ProductField.META_DESCRIPTION,
        ProductField.ALT_TEXT,
        ProductField.SEO_TAGS,
    }
)
MEDIUM_RISK_FIELDS = frozenset({ProductField.TITLE, ProductField.DESCRIPTION})
HIGH_RISK_FIELDS = frozenset({ProductField.PRICE, ProductField.INVENTORY})


def grade_risk(
    operation: OperationType, changed_fields: Collection[ProductField]
) -> RiskLevel:
    """Grade risk deterministically; callers cannot self-declare a level."""
    fields = frozenset(changed_fields)
    if operation in {OperationType.PUBLISH, OperationType.REFUND}:
        return RiskLevel.HIGH
    if not fields:
        raise InvalidRiskInput("An update must change at least one field")
    if fields & HIGH_RISK_FIELDS:
        return RiskLevel.HIGH
    if fields & MEDIUM_RISK_FIELDS:
        return RiskLevel.MEDIUM
    if fields <= LOW_RISK_FIELDS:
        return RiskLevel.LOW
    return RiskLevel.HIGH
