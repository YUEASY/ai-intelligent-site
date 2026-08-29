from uuid import UUID

import pytest

from app.domain.product import CanonicalProduct
from app.domain.risk import ProductField
from app.generation.model_adapter import (
    GeneratedContent,
    ModelInvocation,
    ModelTier,
    ModelUsage,
)
from app.generation.workflow import (
    ALL_CONTENT_FIELDS,
    GenerationError,
    ProductWorkflow,
)
from app.importing.csv_adapter import CsvImportAdapter
from app.platform import RecordingPlatformAdapter
from tests.csv_samples import canonical_row, make_csv

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")

ALL_FIELDS = ALL_CONTENT_FIELDS


def make_product() -> CanonicalProduct:
    return CsvImportAdapter().parse(
        make_csv(canonical_row()), tenant_id=TENANT_ID
    )[0]


class FakeModelAdapter:
    """Deterministic fake that emits the structured I/O contract verbatim."""

    def __init__(self, *, description: str | None = None) -> None:
        self.calls: list[tuple[ModelTier, frozenset[ProductField]]] = []
        self._description = description

    def generate(
        self,
        tier: ModelTier,
        product: CanonicalProduct,
        fields: frozenset[ProductField],
    ) -> ModelInvocation:
        self.calls.append((tier, frozenset(fields)))
        description = None
        if ProductField.DESCRIPTION in fields:
            description = (
                self._description
                if self._description is not None
                else product.description
            )
        content = GeneratedContent(
            title=product.title if ProductField.TITLE in fields else None,
            description=description,
            meta_title=(
                product.meta_title if ProductField.META_TITLE in fields else None
            ),
            meta_description=(
                product.meta_description
                if ProductField.META_DESCRIPTION in fields
                else None
            ),
            alt_text=(
                {image: product.title for image in product.images}
                if ProductField.ALT_TEXT in fields
                else None
            ),
            seo_tags=product.tags if ProductField.SEO_TAGS in fields else None,
        )
        return ModelInvocation(
            content=content,
            usage=ModelUsage(
                tier=tier,
                model=f"fake:{tier.value}",
                input_tokens=1,
                output_tokens=1,
            ),
        )


class IncompleteModelAdapter:
    def generate(
        self,
        tier: ModelTier,
        product: CanonicalProduct,
        fields: frozenset[ProductField],
    ) -> ModelInvocation:
        del product, fields
        return ModelInvocation(
            content=GeneratedContent(),
            usage=ModelUsage(
                tier=tier,
                model=f"fake:{tier.value}",
                input_tokens=0,
                output_tokens=0,
            ),
        )


def test_workflow_generates_all_fields_without_platform_writes() -> None:
    product = make_product()
    fake_model = FakeModelAdapter()
    platform = RecordingPlatformAdapter()
    content = ProductWorkflow(fake_model, platform).generate(product).content

    assert content.title == "Classic T-Shirt"
    assert content.description == "Heavy cotton tee"
    assert content.meta_title == "Classic Cotton T-Shirt"
    assert platform.write_calls == []


def test_workflow_routes_description_to_large_and_rest_to_small() -> None:
    product = make_product()
    fake_model = FakeModelAdapter()
    ProductWorkflow(fake_model, RecordingPlatformAdapter()).generate(product)

    by_tier: dict[ModelTier, set[ProductField]] = {}
    for tier, fields in fake_model.calls:
        by_tier.setdefault(tier, set()).update(fields)
    assert by_tier[ModelTier.LARGE] == {ProductField.DESCRIPTION}
    assert by_tier[ModelTier.SMALL] == ALL_FIELDS - {ProductField.DESCRIPTION}


def test_workflow_rejects_an_incomplete_adapter_output() -> None:
    product = make_product()
    with pytest.raises(GenerationError, match="did not produce"):
        ProductWorkflow(
            IncompleteModelAdapter(), RecordingPlatformAdapter()
        ).generate(product)


def test_workflow_rejects_fabricated_facts() -> None:
    product = make_product()
    fake_model = FakeModelAdapter(description="Now $9.99")
    with pytest.raises(GenerationError, match="not present in product data"):
        ProductWorkflow(fake_model, RecordingPlatformAdapter()).generate(product)
