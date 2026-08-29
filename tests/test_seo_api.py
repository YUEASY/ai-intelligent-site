from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from app.api.platform_deps import get_platform_adapter_factory
from app.api.products import router as products_router
from app.api.reviews import router as reviews_router
from app.database import Base, TenantSession
from app.dependencies import RequestContext, get_request_context
from app.domain.draft import DraftStatus
from app.domain.product import ProductStatus
from app.domain.task_state import TaskState
from app.models import AdminUser, Product, ProductDraft, ProductVariant, Task
from app.platform import RecordingPlatformAdapter
from app.seo import SEO_LOW_RISK_FIELDS

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")

SEO_LOW_FIELDS = {field.value for field in SEO_LOW_RISK_FIELDS}


def make_client() -> tuple[TestClient, Engine]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        session.add(
            Product(
                tenant_id=TENANT_ID,
                source="merchant_csv",
                source_id="product-1",
                sku="TSHIRT",
                title="Classic T-Shirt",
                description="Heavy cotton tee",
                category="Apparel",
                tags=["summer", "cotton"],
                images=["front.jpg"],
                meta_title="Old Meta Title",
                meta_description="Old meta description",
                alt_text={"front.jpg": "Old alt"},
                handle="classic-t-shirt",
                status=ProductStatus.ACTIVE.value,
                shopify_product_id="shopify-123",
                variants=[
                    ProductVariant(
                        tenant_id=TENANT_ID,
                        sku="TSHIRT-BLK-S",
                        options={"Color": "Black", "Size": "S"},
                        price=Decimal("29.90"),
                        cost=Decimal("12.50"),
                        inventory=8,
                        image=None,
                    )
                ],
            )
        )
        session.commit()

    def request_context() -> Iterator[RequestContext]:
        admin = AdminUser(
            id=uuid4(),
            tenant_id=TENANT_ID,
            email="admin@example.com",
            password_hash="unused",
        )
        with TenantSession(
            bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
        ) as session:
            yield RequestContext(
                tenant_id=TENANT_ID,
                actor=admin.email,
                admin=admin,
                session=session,
            )

    adapter = RecordingPlatformAdapter()

    def override_adapter_factory() -> object:
        return lambda tenant_id: adapter

    app = FastAPI()
    app.include_router(products_router, prefix="/api/v1")
    app.include_router(reviews_router, prefix="/api/v1")
    app.dependency_overrides[get_request_context] = request_context
    app.dependency_overrides[get_platform_adapter_factory] = (
        override_adapter_factory
    )
    return TestClient(app), engine


def _product_id(client: TestClient) -> str:
    return client.get("/api/v1/products").json()[0]["id"]


def test_seo_endpoint_creates_a_low_risk_task_and_dispatches() -> None:
    client, _ = make_client()
    product_id = _product_id(client)

    with patch("app.api.products.execute_task") as mock_execute:
        response = client.post(f"/api/v1/products/{product_id}/seo", json={})

    assert response.status_code == 202
    body = response.json()
    assert body["kind"] == "seo"
    assert body["risk_level"] == "low"
    assert body["product_id"] == product_id
    assert set(body["changed_fields"]) == SEO_LOW_FIELDS
    mock_execute.delay.assert_called_once()


def test_seo_endpoint_creates_a_medium_risk_task_when_title_requested() -> None:
    client, _ = make_client()
    product_id = _product_id(client)

    with patch("app.api.products.execute_task"):
        response = client.post(
            f"/api/v1/products/{product_id}/seo", json={"include_title": True}
        )

    assert response.status_code == 202
    body = response.json()
    assert body["risk_level"] == "medium"
    assert "title" in body["changed_fields"]


def test_seo_endpoint_rejects_an_unpublished_product() -> None:
    client, engine = make_client()
    product_id = _product_id(client)

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = session.get(Product, UUID(product_id))
        assert product is not None
        product.status = ProductStatus.DRAFT.value
        product.shopify_product_id = None
        session.commit()

    response = client.post(f"/api/v1/products/{product_id}/seo", json={})
    assert response.status_code == 409


def test_seo_endpoint_rejects_an_unknown_product() -> None:
    client, _ = make_client()
    missing = "00000000-0000-0000-0000-00000000abcd"

    response = client.post(f"/api/v1/products/{missing}/seo", json={})
    assert response.status_code == 404


def test_review_queue_exposes_seo_kind_and_task_status() -> None:
    client, engine = make_client()
    product_id = _product_id(client)

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = session.get(Product, UUID(product_id))
        assert product is not None
        seo_task = Task(
            tenant_id=TENANT_ID,
            kind="seo",
            operation_type="update",
            changed_fields=["meta_title"],
            risk_level="low",
            status=TaskState.PUBLISHED.value,
            product_id=product.id,
        )
        session.add(seo_task)
        session.flush()
        session.add(
            ProductDraft(
                tenant_id=TENANT_ID,
                product_id=product.id,
                task_id=seo_task.id,
                title=product.title,
                description=product.description,
                meta_title="Optimized Meta Title",
                meta_description=product.meta_description,
                alt_text=product.alt_text,
                seo_tags=product.tags,
                risk_level="low",
                status=DraftStatus.PUBLISHED.value,
            )
        )
        session.commit()

    queue = client.get("/api/v1/reviews/queue")
    assert queue.status_code == 200
    items = queue.json()
    assert len(items) == 1
    assert items[0]["kind"] == "seo"
    assert items[0]["task_status"] == "published"
    assert items[0]["status"] == "published"
    assert items[0]["meta_title"] == "Optimized Meta Title"
