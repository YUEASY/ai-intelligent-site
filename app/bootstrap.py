from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.auth import hash_password
from app.config import Settings
from app.database import InfrastructureSessionFactory
from app.domain.draft import DraftStatus
from app.domain.product import ProductStatus
from app.domain.risk import OperationType, ProductField, RiskLevel
from app.domain.task_state import TaskState
from app.models import (
    AdminUser,
    Product,
    ProductDraft,
    ProductVariant,
    Task,
    TaskAuditLog,
)


@dataclass(frozen=True)
class DemoProduct:
    source_id: str
    sku: str
    title: str
    generated_title: str
    description: str
    generated_description: str
    category: str
    tags: list[str]
    price: Decimal
    cost: Decimal
    inventory: int
    risk_level: RiskLevel
    changed_fields: list[ProductField]
    draft_status: DraftStatus = DraftStatus.PENDING_REVIEW
    image_url: str | None = None


DEMO_PRODUCTS = (
    DemoProduct(
        source_id="bamboo-travel-mug",
        sku="DEMO-MUG",
        title="Bamboo Travel Mug",
        generated_title="Eco Bamboo Travel Mug with Leak-Resistant Lid",
        description="A reusable travel mug with a bamboo-fibre outer shell.",
        generated_description=(
            "Take your daily coffee anywhere with a lightweight reusable mug, "
            "a secure lid, and a naturally textured bamboo-fibre finish."
        ),
        category="Drinkware",
        tags=["eco-friendly", "travel", "drinkware"],
        price=Decimal("24.90"),
        cost=Decimal("8.40"),
        inventory=86,
        risk_level=RiskLevel.LOW,
        changed_fields=[
            ProductField.META_TITLE,
            ProductField.META_DESCRIPTION,
            ProductField.SEO_TAGS,
        ],
        image_url=(
            "https://images.pexels.com/photos/13697747/"
            "pexels-photo-13697747.jpeg?auto=compress&cs=tinysrgb&w=1200"
        ),
    ),
    DemoProduct(
        source_id="linen-weekender-bag",
        sku="DEMO-BAG",
        title="Linen Weekender Bag",
        generated_title="Lightweight Linen Weekender Bag for Short Trips",
        description="A roomy linen-blend bag for weekends and cabin luggage.",
        generated_description=(
            "Pack smarter for short trips with a soft linen-blend weekender, "
            "reinforced handles, and a spacious zippered interior."
        ),
        category="Travel Bags",
        tags=["linen", "weekender", "travel"],
        price=Decimal("68.00"),
        cost=Decimal("25.50"),
        inventory=34,
        risk_level=RiskLevel.MEDIUM,
        changed_fields=[ProductField.TITLE, ProductField.DESCRIPTION],
    ),
    DemoProduct(
        source_id="wireless-desk-lamp",
        sku="DEMO-LAMP",
        title="Wireless Desk Lamp",
        generated_title="Dimmable Wireless Desk Lamp with USB-C Charging",
        description="A rechargeable desk lamp with adjustable brightness.",
        generated_description=(
            "Create a focused workspace with adjustable warm-to-cool light, "
            "touch controls, and convenient USB-C recharging."
        ),
        category="Lighting",
        tags=["desk", "lighting", "wireless"],
        price=Decimal("49.00"),
        cost=Decimal("18.20"),
        inventory=19,
        risk_level=RiskLevel.HIGH,
        changed_fields=[ProductField.PRICE, ProductField.INVENTORY],
    ),
    DemoProduct(
        source_id="organic-cotton-throw",
        sku="DEMO-THROW",
        title="Organic Cotton Throw",
        generated_title="Soft Organic Cotton Throw for Sofa and Bed",
        description="A breathable woven throw made with organic cotton.",
        generated_description=(
            "Add an easy layer of warmth with a breathable organic-cotton "
            "throw designed for sofas, reading chairs, and beds."
        ),
        category="Home Textiles",
        tags=["organic cotton", "home", "throw"],
        price=Decimal("42.00"),
        cost=Decimal("15.00"),
        inventory=52,
        risk_level=RiskLevel.MEDIUM,
        changed_fields=[ProductField.TITLE, ProductField.DESCRIPTION],
        draft_status=DraftStatus.APPROVED,
    ),
)


def ensure_bootstrap_admin(settings: Settings) -> None:
    with InfrastructureSessionFactory.begin() as session:
        existing = session.scalar(
            select(AdminUser).where(
                AdminUser.tenant_id == settings.bootstrap_tenant_id,
                AdminUser.email == settings.bootstrap_admin_email,
            )
        )
        if existing is not None:
            return
        session.add(
            AdminUser(
                tenant_id=settings.bootstrap_tenant_id,
                email=settings.bootstrap_admin_email,
                password_hash=hash_password(
                    settings.bootstrap_admin_password.get_secret_value()
                ),
            )
        )


def ensure_bootstrap_demo_data(settings: Settings) -> None:
    """Seed local-only showcase records without creating a Shopify store."""
    if settings.environment != "development" or not settings.bootstrap_demo_data:
        return

    with InfrastructureSessionFactory.begin() as session:
        for spec in DEMO_PRODUCTS:
            existing = session.scalar(
                select(Product).where(
                    Product.tenant_id == settings.bootstrap_tenant_id,
                    Product.source == "demo",
                    Product.source_id == spec.source_id,
                )
            )
            if existing is not None:
                expected_images = [spec.image_url] if spec.image_url else []
                if existing.images != expected_images:
                    existing.images = expected_images
                continue

            product = Product(
                tenant_id=settings.bootstrap_tenant_id,
                source="demo",
                source_id=spec.source_id,
                sku=spec.sku,
                title=spec.title,
                description=spec.description,
                category=spec.category,
                tags=spec.tags,
                images=[spec.image_url] if spec.image_url else [],
                meta_title=spec.title,
                meta_description=spec.description,
                handle=spec.source_id,
                status=ProductStatus.DRAFT.value,
                variants=[
                    ProductVariant(
                        tenant_id=settings.bootstrap_tenant_id,
                        sku=f"{spec.sku}-DEFAULT",
                        options={"Title": "Default"},
                        price=spec.price,
                        cost=spec.cost,
                        inventory=spec.inventory,
                        image=None,
                    )
                ],
            )
            session.add(product)
            session.flush()

            task_status = (
                TaskState.APPROVED
                if spec.draft_status is DraftStatus.APPROVED
                else TaskState.AWAITING_REVIEW
            )
            task = Task(
                tenant_id=settings.bootstrap_tenant_id,
                kind="product",
                operation_type=OperationType.UPDATE.value,
                changed_fields=[field.value for field in spec.changed_fields],
                risk_level=spec.risk_level.value,
                status=task_status.value,
                product_id=product.id,
            )
            session.add(task)
            session.flush()
            transitions = [
                (TaskState.PENDING, TaskState.RUNNING),
                (TaskState.RUNNING, TaskState.AWAITING_REVIEW),
            ]
            if task_status is TaskState.APPROVED:
                transitions.append(
                    (TaskState.AWAITING_REVIEW, TaskState.APPROVED)
                )
            session.add_all(
                [
                    TaskAuditLog(
                        tenant_id=settings.bootstrap_tenant_id,
                        task_id=task.id,
                        actor="demo-seed",
                        from_status=from_status.value,
                        to_status=to_status.value,
                    )
                    for from_status, to_status in transitions
                ]
            )
            session.add(
                ProductDraft(
                    tenant_id=settings.bootstrap_tenant_id,
                    product_id=product.id,
                    task_id=task.id,
                    title=spec.generated_title,
                    description=spec.generated_description,
                    meta_title=spec.generated_title,
                    meta_description=spec.generated_description,
                    alt_text={},
                    seo_tags=spec.tags,
                    risk_level=spec.risk_level.value,
                    status=spec.draft_status.value,
                )
            )
