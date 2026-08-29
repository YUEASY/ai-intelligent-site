"""Product generation workflow (seam A orchestration layer).

The workflow depends only on adapter interfaces, so tests drive it end to end
with a fake Model Adapter and a recording Platform Adapter.  Generation never
writes to the platform: the Platform Adapter is reserved for the publish stage
and must observe zero calls during this stage.
"""

from collections.abc import Collection

from app.domain.product import CanonicalProduct
from app.domain.risk import ProductField
from app.generation.model_adapter import (
    DeterministicModelAdapter,
    GeneratedContent,
    ModelAdapter,
    check_facts,
    group_fields_by_tier,
)
from app.generation.rules import ContentRuleValidator, GenerationRuleViolation
from app.platform import NoopPlatformAdapter, PlatformAdapter

ALL_CONTENT_FIELDS = frozenset(
    {
        ProductField.TITLE,
        ProductField.DESCRIPTION,
        ProductField.META_TITLE,
        ProductField.META_DESCRIPTION,
        ProductField.ALT_TEXT,
        ProductField.SEO_TAGS,
    }
)


class GenerationError(RuntimeError):
    """Generation produced content that failed a deterministic gate."""


class ProductWorkflow:
    """Orchestrates content generation without touching the storefront."""

    def __init__(
        self,
        model_adapter: ModelAdapter,
        platform_adapter: PlatformAdapter,
        validator: ContentRuleValidator | None = None,
    ) -> None:
        self._model_adapter = model_adapter
        self._platform_adapter = platform_adapter
        self._validator = validator or ContentRuleValidator()

    def generate(
        self,
        product: CanonicalProduct,
        fields: Collection[ProductField] = ALL_CONTENT_FIELDS,
    ) -> GeneratedContent:
        requested = frozenset(fields)
        content = GeneratedContent()
        for tier, tier_fields in group_fields_by_tier(requested).items():
            content = _merge(
                content, self._model_adapter.generate(tier, product, tier_fields)
            )

        self._ensure_complete(content, requested)
        self._enforce_rules(content)
        self._enforce_facts(content, product)
        return content

    def _ensure_complete(
        self, content: GeneratedContent, requested: frozenset[ProductField]
    ) -> None:
        # ProductField values mirror GeneratedContent field names, so the
        # requested field's value is its attribute of the same name.
        missing = [
            field.value
            for field in requested
            if getattr(content, field.value) is None
        ]
        if missing:
            raise GenerationError(
                "model adapter did not produce: " + ", ".join(missing)
            )

    def _enforce_rules(self, content: GeneratedContent) -> None:
        violations = self._validator.validate(content)
        if violations:
            raise GenerationError(_describe_rule_violations(violations))

    def _enforce_facts(
        self, content: GeneratedContent, product: CanonicalProduct
    ) -> None:
        violations = check_facts(content, product)
        if violations:
            raise GenerationError(
                "; ".join(violation.message for violation in violations)
            )


def _merge(base: GeneratedContent, partial: GeneratedContent) -> GeneratedContent:
    merged = base.model_dump()
    merged.update(partial.model_dump(exclude_none=True))
    return GeneratedContent.model_validate(merged)


def _describe_rule_violations(
    violations: list[GenerationRuleViolation],
) -> str:
    return "; ".join(
        f"{v.field.value if v.field else 'content'}: {v.message}"
        for v in violations
    )


def build_default_workflow() -> ProductWorkflow:
    """Development/test workflow backed by a deterministic, fact-safe adapter."""

    return ProductWorkflow(
        model_adapter=DeterministicModelAdapter(),
        platform_adapter=NoopPlatformAdapter(),
    )
