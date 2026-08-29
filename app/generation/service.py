"""DB-aware generation services: draft persistence and review queue."""

from sqlalchemy import case, select

from app.database import TenantSession
from app.domain.draft import DraftStatus
from app.domain.product import CanonicalProduct, CanonicalVariant, ProductStatus
from app.domain.risk import ProductField, RiskLevel
from app.generation.model_adapter import GeneratedContent
from app.generation.workflow import (
    GenerationError,
    ProductWorkflow,
    build_default_workflow,
)
from app.models import Product, ProductDraft, Task
from app.product_service import ProductNotFoundError, ProductService


class DraftNotFoundError(LookupError):
    pass


def to_canonical_product(product: Product) -> CanonicalProduct:
    return CanonicalProduct(
        tenant_id=product.tenant_id,
        source=product.source,
        source_id=product.source_id,
        sku=product.sku,
        title=product.title,
        description=product.description,
        category=product.category,
        tags=product.tags,
        images=product.images,
        meta_title=product.meta_title,
        meta_description=product.meta_description,
        handle=product.handle,
        status=ProductStatus(product.status),
        variants=[
            CanonicalVariant(
                sku=variant.sku,
                options=variant.options,
                price=variant.price,
                cost=variant.cost,
                inventory=variant.inventory,
                image=variant.image,
            )
            for variant in product.variants
        ],
    )


class DraftService:
    def __init__(self, session: TenantSession) -> None:
        self._session = session

    def create(
        self,
        task: Task,
        content: GeneratedContent,
        risk_level: RiskLevel,
    ) -> ProductDraft:
        if task.product_id is None:
            raise GenerationError("task has no product to generate for")
        if (
            content.title is None
            or content.description is None
            or content.meta_title is None
            or content.meta_description is None
            or content.alt_text is None
            or content.seo_tags is None
        ):
            raise GenerationError("cannot persist an incomplete draft")
        draft = ProductDraft(
            tenant_id=self._session.tenant_id,
            product_id=task.product_id,
            task_id=task.id,
            title=content.title,
            description=content.description,
            meta_title=content.meta_title,
            meta_description=content.meta_description,
            alt_text=content.alt_text,
            seo_tags=content.seo_tags,
            risk_level=risk_level.value,
            status=DraftStatus.PENDING_REVIEW.value,
        )
        self._session.add(draft)
        self._session.flush()
        return draft

    def review_queue(self) -> list[ProductDraft]:
        """Drafts awaiting human review, sorted by tenant + risk + created time.

        Risk ordering is high → medium → low so the riskiest items surface first.
        """

        risk_rank = case(
            (ProductDraft.risk_level == RiskLevel.HIGH.value, 0),
            (ProductDraft.risk_level == RiskLevel.MEDIUM.value, 1),
            (ProductDraft.risk_level == RiskLevel.LOW.value, 2),
            else_=3,
        )
        statement = (
            select(ProductDraft)
            .where(ProductDraft.status == DraftStatus.PENDING_REVIEW.value)
            .order_by(
                ProductDraft.tenant_id,
                risk_rank,
                ProductDraft.created_at,
                ProductDraft.id,
            )
        )
        return list(self._session.scalars(statement))


class GenerationService:
    """Run generation for a task and store the resulting draft.

    Generation always lands in a ``pending_review`` draft — publishing is a
    later stage — but the risk level is recorded so that stage can route
    low-risk drafts automatically and medium/high-risk drafts to a human.
    """

    def __init__(
        self, session: TenantSession, workflow: ProductWorkflow | None = None
    ) -> None:
        self._session = session
        self._workflow = workflow or build_default_workflow()

    def generate(self, task: Task) -> ProductDraft:
        if task.product_id is None:
            raise ProductNotFoundError("task has no product to generate for")
        product = ProductService(self._session).get(task.product_id)
        canonical = to_canonical_product(product)
        fields = [ProductField(field) for field in task.changed_fields]
        content = self._workflow.generate(canonical, fields)
        return DraftService(self._session).create(
            task,
            content,
            RiskLevel(task.risk_level),
        )
