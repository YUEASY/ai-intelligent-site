from uuid import UUID

from app.domain.product import CanonicalProduct
from app.domain.risk import ProductField
from app.generation.model_adapter import (
    DeterministicModelAdapter,
    GeneratedContent,
    ModelTier,
    check_facts,
    group_fields_by_tier,
    model_tier_for_field,
)
from app.generation.workflow import ALL_CONTENT_FIELDS as CONTENT_FIELDS
from app.importing.csv_adapter import CsvImportAdapter
from tests.csv_samples import canonical_row, make_csv

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_product() -> CanonicalProduct:
    return CsvImportAdapter().parse(
        make_csv(canonical_row()), tenant_id=TENANT_ID
    )[0]


def test_description_routes_to_the_large_model() -> None:
    assert model_tier_for_field(ProductField.DESCRIPTION) is ModelTier.LARGE


def test_short_fields_route_to_the_small_model() -> None:
    for field in (
        ProductField.TITLE,
        ProductField.META_TITLE,
        ProductField.META_DESCRIPTION,
        ProductField.ALT_TEXT,
        ProductField.SEO_TAGS,
    ):
        assert model_tier_for_field(field) is ModelTier.SMALL


def test_fields_group_by_model_tier() -> None:
    grouped = group_fields_by_tier(
        frozenset({ProductField.TITLE, ProductField.DESCRIPTION})
    )
    assert grouped == {
        ModelTier.SMALL: frozenset({ProductField.TITLE}),
        ModelTier.LARGE: frozenset({ProductField.DESCRIPTION}),
    }


def test_deterministic_adapter_derives_content_from_real_product_data() -> None:
    product = make_product()
    content = DeterministicModelAdapter().generate(
        ModelTier.SMALL, product, CONTENT_FIELDS
    ).content
    assert content.title == "Classic T-Shirt"
    assert content.description == "Heavy cotton tee"
    assert content.meta_title == "Classic Cotton T-Shirt"
    assert content.meta_description == "Shop our classic cotton T-shirt"
    assert content.alt_text == {
        "front.jpg": "Classic T-Shirt Apparel",
        "back.jpg": "Classic T-Shirt Apparel",
    }
    assert content.seo_tags == ["Apparel", "cotton", "summer"]


def test_deterministic_adapter_fills_only_requested_fields() -> None:
    product = make_product()
    content = DeterministicModelAdapter().generate(
        ModelTier.SMALL, product, frozenset({ProductField.TITLE})
    ).content
    assert content.title == "Classic T-Shirt"
    assert content.description is None
    assert content.seo_tags is None


def test_check_facts_accepts_a_real_product_price() -> None:
    product = make_product()
    content = GeneratedContent(description="Only $29.90 for this tee")
    assert check_facts(content, product) == []


def test_check_facts_rejects_a_fabricated_price() -> None:
    product = make_product()
    content = GeneratedContent(description="Now $9.99")
    violations = check_facts(content, product)
    assert len(violations) == 1
    assert "9.99" in violations[0].message
