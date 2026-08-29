"""SEO optimization workflow service.

Reads already-published products and generates SEO content (meta title, meta
description, image alt text, and SEO tags).  Low-risk updates are applied to the
storefront automatically after deterministic rule validation; medium- and
high-risk changes (such as the title) become a draft awaiting human review.
Both paths reuse the publish/snapshot/rollback machinery so every write is
versioned and rollback-able.
"""

from app.database import TenantSession
from app.domain.draft import DraftStatus
from app.domain.product import CanonicalProduct, ProductStatus
from app.domain.risk import ProductField, RiskLevel
from app.domain.snapshot import apply_draft_to_state, product_state
from app.domain.task_state import TaskState
from app.generation.model_adapter import GeneratedContent
from app.generation.service import DraftService, to_canonical_product
from app.generation.workflow import (
    GenerationError,
    ProductWorkflow,
    build_default_workflow,
)
from app.models import Product, Task
from app.platform import PlatformAdapter
from app.product_service import ProductService
from app.publish_service import write_product_state
from app.services import TaskService

SEO_LOW_RISK_FIELDS = frozenset(
    {
        ProductField.META_TITLE,
        ProductField.META_DESCRIPTION,
        ProductField.ALT_TEXT,
        ProductField.SEO_TAGS,
    }
)
SEO_TITLE_FIELDS = frozenset({ProductField.TITLE})
SEO_ALL_FIELDS = SEO_LOW_RISK_FIELDS | SEO_TITLE_FIELDS


class SeoProductNotPublished(ValueError):
    pass


def is_published(product: Product) -> bool:
    """A product is optimizable once it is active and has a Shopify id."""
    return (
        product.status == ProductStatus.ACTIVE.value
        and product.shopify_product_id is not None
    )


def _complete_content(
    product: CanonicalProduct, generated: GeneratedContent
) -> GeneratedContent:
    """Fill fields the SEO workflow does not generate from the product.

    SEO only regenerates Meta / Alt / SEO tags (and, for medium risk, the
    title); description and any untouched field fall back to the product's own
    values so a complete draft and a complete write payload can be produced.
    """

    return GeneratedContent(
        title=generated.title if generated.title is not None else product.title,
        description=(
            generated.description
            if generated.description is not None
            else product.description
        ),
        meta_title=(
            generated.meta_title
            if generated.meta_title is not None
            else product.meta_title
        ),
        meta_description=(
            generated.meta_description
            if generated.meta_description is not None
            else product.meta_description
        ),
        alt_text=(
            generated.alt_text
            if generated.alt_text is not None
            else dict(product.alt_text)
        ),
        seo_tags=(
            generated.seo_tags if generated.seo_tags is not None else list(product.tags)
        ),
    )


class SeoService:
    """Run the SEO workflow for a task against a store-backed adapter."""

    def __init__(
        self,
        session: TenantSession,
        actor: str,
        workflow: ProductWorkflow | None = None,
    ) -> None:
        self._session = session
        self._actor = actor
        self._workflow = workflow or build_default_workflow()

    def run(self, task: Task, adapter: PlatformAdapter) -> TaskState:
        """Generate SEO content and either auto-write it or queue it for review."""
        if task.product_id is None:
            raise SeoProductNotPublished("SEO task has no product to optimize")
        product = ProductService(self._session).get(task.product_id)
        if not is_published(product):
            raise SeoProductNotPublished(f"Product {product.id} is not published yet")

        canonical = to_canonical_product(product)
        fields = [ProductField(field) for field in task.changed_fields]
        try:
            content = self._workflow.generate(canonical, fields)
        except GenerationError as exc:
            if exc.content is not None:
                DraftService(self._session).create(
                    task,
                    _complete_content(canonical, exc.content),
                    RiskLevel(task.risk_level),
                    status=DraftStatus.PENDING_REVIEW,
                )
            TaskService(self._session, self._actor).fail(task.id, str(exc))
            self._session.flush()
            return TaskState.FAILED
        complete = _complete_content(canonical, content)

        if RiskLevel(task.risk_level) is RiskLevel.LOW:
            return self._auto_update(task, product, complete, adapter)
        return self._await_review(task, complete)

    def _auto_update(
        self,
        task: Task,
        product: Product,
        content: GeneratedContent,
        adapter: PlatformAdapter,
    ) -> TaskState:
        # Record the suggestion before the write so a failed auto-update still
        # surfaces in the review queue (task failed + pending suggestion).
        draft = DraftService(self._session).create(
            task,
            content,
            RiskLevel(task.risk_level),
            status=DraftStatus.PENDING_REVIEW,
        )
        TaskService(self._session, self._actor).advance(task.id, TaskState.SUGGESTED)
        self._session.commit()

        before = product_state(product)
        after = apply_draft_to_state(before, content)
        write = write_product_state(
            self._session, self._actor, adapter, product, before, after
        )
        receipt = write.receipt
        if not receipt.success:
            TaskService(self._session, self._actor).fail(
                task.id,
                receipt.error or "Shopify did not confirm the SEO update",
            )
            self._session.flush()
            return TaskState.FAILED

        TaskService(self._session, self._actor).advance(task.id, TaskState.PUBLISHED)
        draft.status = DraftStatus.PUBLISHED.value
        self._session.flush()
        return TaskState.PUBLISHED

    def _await_review(self, task: Task, content: GeneratedContent) -> TaskState:
        DraftService(self._session).create(
            task,
            content,
            RiskLevel(task.risk_level),
            status=DraftStatus.PENDING_REVIEW,
        )
        TaskService(self._session, self._actor).advance(
            task.id, TaskState.AWAITING_REVIEW
        )
        self._session.flush()
        return TaskState.AWAITING_REVIEW
