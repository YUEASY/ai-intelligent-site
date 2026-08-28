import pytest

from app.domain.risk import (
    InvalidRiskInput,
    OperationType,
    ProductField,
    RiskLevel,
    grade_risk,
)


@pytest.mark.parametrize(
    "fields",
    [
        {ProductField.META_TITLE},
        {ProductField.META_DESCRIPTION, ProductField.ALT_TEXT},
        {ProductField.SEO_TAGS},
    ],
)
def test_content_update_with_only_whitelisted_fields_is_low_risk(
    fields: set[ProductField],
) -> None:
    assert grade_risk(OperationType.UPDATE, fields) is RiskLevel.LOW


@pytest.mark.parametrize("fields", [{ProductField.TITLE}, {ProductField.DESCRIPTION}])
def test_content_update_with_customer_facing_copy_is_medium_risk(
    fields: set[ProductField],
) -> None:
    assert grade_risk(OperationType.UPDATE, fields) is RiskLevel.MEDIUM


@pytest.mark.parametrize(
    ("operation", "fields"),
    [
        (OperationType.UPDATE, {ProductField.PRICE}),
        (OperationType.UPDATE, {ProductField.INVENTORY}),
        (OperationType.PUBLISH, set()),
        (OperationType.REFUND, set()),
    ],
)
def test_commercial_or_irreversible_changes_are_high_risk(
    operation: OperationType, fields: set[ProductField]
) -> None:
    assert grade_risk(operation, fields) is RiskLevel.HIGH


def test_highest_risk_field_wins_for_a_mixed_update() -> None:
    assert (
        grade_risk(
            OperationType.UPDATE,
            {ProductField.META_TITLE, ProductField.TITLE, ProductField.PRICE},
        )
        is RiskLevel.HIGH
    )


def test_update_without_fields_is_rejected() -> None:
    with pytest.raises(InvalidRiskInput, match="at least one field"):
        grade_risk(OperationType.UPDATE, set())
