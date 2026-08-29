from app.domain.risk import ProductField
from app.generation.model_adapter import GeneratedContent
from app.generation.rules import ContentRuleValidator


def make_content(**overrides: object) -> GeneratedContent:
    values: dict[str, object] = {
        "title": "Classic T-Shirt",
        "description": "Heavy cotton tee",
        "meta_title": "Classic Cotton T-Shirt",
        "meta_description": "Shop our classic cotton T-shirt",
        "alt_text": {"front.jpg": "Classic T-Shirt"},
        "seo_tags": ["cotton", "summer"],
    }
    values.update(overrides)
    return GeneratedContent.model_validate(values)


def test_length_rule_flags_an_oversized_meta_title() -> None:
    content = make_content(meta_title="x" * 256)
    violations = ContentRuleValidator().validate(content)
    assert any(
        violation.field is ProductField.META_TITLE for violation in violations
    )


def test_banned_word_rule_flags_default_banned_words() -> None:
    content = make_content(description="A replica watch")
    violations = ContentRuleValidator().validate(content)
    assert any("replica" in violation.message for violation in violations)


def test_duplicate_title_rule_flags_a_title_used_by_the_catalog() -> None:
    content = make_content(title="Classic T-Shirt")
    violations = ContentRuleValidator(
        existing_titles=["classic t-shirt"]
    ).validate(content)
    assert any(
        violation.field is ProductField.TITLE for violation in violations
    )


def test_valid_content_passes_every_rule() -> None:
    content = make_content()
    assert ContentRuleValidator().validate(content) == []
