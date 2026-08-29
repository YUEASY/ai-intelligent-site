"""Generation package: Model Adapter seam, deterministic rules and workflow."""

from app.generation.model_adapter import (
    DeterministicModelAdapter,
    FactViolation,
    GeneratedContent,
    ModelAdapter,
    ModelTier,
    check_facts,
    group_fields_by_tier,
    model_tier_for_field,
)
from app.generation.rules import ContentRuleValidator, GenerationRuleViolation
from app.generation.workflow import (
    GenerationError,
    ProductWorkflow,
    build_default_workflow,
)

__all__ = [
    "ContentRuleValidator",
    "DeterministicModelAdapter",
    "FactViolation",
    "GeneratedContent",
    "GenerationError",
    "GenerationRuleViolation",
    "ModelAdapter",
    "ModelTier",
    "ProductWorkflow",
    "build_default_workflow",
    "check_facts",
    "group_fields_by_tier",
    "model_tier_for_field",
]
