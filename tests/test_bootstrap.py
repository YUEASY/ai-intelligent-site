from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import bootstrap
from app.config import Settings
from app.database import Base, TenantSession
from app.domain.draft import DraftStatus
from app.generation.service import DraftService
from app.models import Product, ProductDraft, ShopifyStore, TaskAuditLog


def test_demo_seed_is_development_only_idempotent_and_shopify_free(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        bootstrap, "InfrastructureSessionFactory", sessionmaker(bind=engine)
    )
    settings = Settings(
        environment="development",
        bootstrap_demo_data=True,
    )

    bootstrap.ensure_bootstrap_demo_data(settings)
    bootstrap.ensure_bootstrap_demo_data(settings)

    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Product)) == 4
        assert (
            connection.scalar(select(func.count()).select_from(ProductDraft)) == 4
        )
        assert connection.scalar(select(func.count()).select_from(ShopifyStore)) == 0
        assert connection.scalar(select(func.count()).select_from(TaskAuditLog)) == 9
        statuses = set(
            connection.scalars(select(ProductDraft.status)).all()
        )
        assert statuses == {
            DraftStatus.PENDING_REVIEW.value,
            DraftStatus.APPROVED.value,
        }
        mug_images = connection.scalar(
            select(Product.images).where(Product.source_id == "bamboo-travel-mug")
        )
        assert mug_images is not None
        assert mug_images[0].startswith("https://images.pexels.com/")
    with TenantSession(
        bind=engine,
        expire_on_commit=False,
        tenant_id=settings.bootstrap_tenant_id,
    ) as tenant_session:
        assert len(DraftService(tenant_session).review_queue()) == 4


def test_demo_seed_can_be_disabled(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        bootstrap, "InfrastructureSessionFactory", sessionmaker(bind=engine)
    )

    bootstrap.ensure_bootstrap_demo_data(
        Settings(environment="development", bootstrap_demo_data=False)
    )
    production_settings = Settings().model_copy(
        update={"environment": "production", "bootstrap_demo_data": True}
    )
    bootstrap.ensure_bootstrap_demo_data(production_settings)

    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Product)) == 0
