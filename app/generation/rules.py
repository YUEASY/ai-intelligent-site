"""Deterministic content rules.

These checks run without any model call and gate every generated draft:
length, banned words, and duplicate titles against the tenant's catalog.
"""

from collections.abc import Collection
from dataclasses import dataclass

from pydantic import BaseModel

from app.domain.risk import ProductField
from app.generation.model_adapter import GeneratedContent

# Placeholder compliance policy for cross-border listings; the merchant-level
# policy is expected to extend this per store.
DEFAULT_BANNED_WORDS: frozenset[str] = frozenset(
    {"counterfeit", "replica", "fake"}
)


@dataclass(frozen=True)
class FieldLimits:
    min_length: int
    max_length: int


FIELD_LIMITS: dict[ProductField, FieldLimits] = {
    ProductField.TITLE: FieldLimits(1, 255),
    ProductField.DESCRIPTION: FieldLimits(1, 10_000),
    ProductField.META_TITLE: FieldLimits(1, 255),
    ProductField.META_DESCRIPTION: FieldLimits(1, 320),
    ProductField.ALT_TEXT: FieldLimits(1, 200),
    ProductField.SEO_TAGS: FieldLimits(1, 64),
}


class GenerationRuleViolation(BaseModel):
    field: ProductField | None
    message: str


class ContentRuleValidator:
    """Apply deterministic content rules to generated output."""

    def __init__(
        self,
        *,
        banned_words: Collection[str] = DEFAULT_BANNED_WORDS,
        existing_titles: Collection[str] = (),
    ) -> None:
        self._banned = {word.casefold() for word in banned_words}
        self._existing_titles = {title.casefold() for title in existing_titles}

    def validate(self, content: GeneratedContent) -> list[GenerationRuleViolation]:
        violations: list[GenerationRuleViolation] = []
        violations.extend(self._check_lengths(content))
        violations.extend(self._check_banned_words(content))
        violations.extend(self._check_duplicate_title(content))
        return violations

    def _check_lengths(
        self, content: GeneratedContent
    ) -> list[GenerationRuleViolation]:
        violations: list[GenerationRuleViolation] = []
        scalar_fields = (
            (ProductField.TITLE, content.title),
            (ProductField.DESCRIPTION, content.description),
            (ProductField.META_TITLE, content.meta_title),
            (ProductField.META_DESCRIPTION, content.meta_description),
        )
        for field, value in scalar_fields:
            if value is None:
                continue
            limits = FIELD_LIMITS[field]
            if not limits.min_length <= len(value) <= limits.max_length:
                violations.append(
                    GenerationRuleViolation(
                        field=field,
                        message=(
                            f"length {len(value)} outside "
                            f"[{limits.min_length}, {limits.max_length}]"
                        ),
                    )
                )
        if content.alt_text is not None:
            for reference, alt in content.alt_text.items():
                limits = FIELD_LIMITS[ProductField.ALT_TEXT]
                if not limits.min_length <= len(alt) <= limits.max_length:
                    violations.append(
                        GenerationRuleViolation(
                            field=ProductField.ALT_TEXT,
                            message=(
                                f"alt text for {reference} has length {len(alt)} "
                                f"outside [{limits.min_length}, {limits.max_length}]"
                            ),
                        )
                    )
        if content.seo_tags is not None:
            for tag in content.seo_tags:
                limits = FIELD_LIMITS[ProductField.SEO_TAGS]
                if not limits.min_length <= len(tag) <= limits.max_length:
                    violations.append(
                        GenerationRuleViolation(
                            field=ProductField.SEO_TAGS,
                            message=(
                                f"tag {tag!r} has length {len(tag)} outside "
                                f"[{limits.min_length}, {limits.max_length}]"
                            ),
                        )
                    )
        return violations

    def _check_banned_words(
        self, content: GeneratedContent
    ) -> list[GenerationRuleViolation]:
        if not self._banned:
            return []
        texts = (
            content.title,
            content.description,
            content.meta_title,
            content.meta_description,
            *(content.seo_tags or []),
            *(content.alt_text or {}).values(),
        )
        violations: list[GenerationRuleViolation] = []
        for text in texts:
            if text is None:
                continue
            lowered = text.casefold()
            for word in self._banned:
                if word in lowered:
                    violations.append(
                        GenerationRuleViolation(
                            field=None,
                            message=f"banned word {word!r} present",
                        )
                    )
        return violations

    def _check_duplicate_title(
        self, content: GeneratedContent
    ) -> list[GenerationRuleViolation]:
        if content.title is None or not self._existing_titles:
            return []
        if content.title.casefold() in self._existing_titles:
            return [
                GenerationRuleViolation(
                    field=ProductField.TITLE,
                    message="generated title duplicates an existing product title",
                )
            ]
        return []
