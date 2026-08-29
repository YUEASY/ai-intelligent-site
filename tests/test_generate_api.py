from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from app.api.products import router as products_router
from app.api.reviews import router as reviews_router
from app.database import Base, TenantSession
from app.dependencies import RequestContext, get_request_context
from app.models import AdminUser, Product, ProductVariant
from app.worker import run_task_workflow

TENANT_A = UUID("00000000-0000-0000-0000-000000000001")


def make_client() -> tuple[TestClient, Engine]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_A
    ) as session:
        session.add(
            Product(
                tenant_id=TENANT_A,
                source="merchant_csv",
                source_id="product-1",
                sku="TSHIRT",
                title="Classic T-Shirt",
                description="Heavy cotton tee",
                category="Apparel",
                tags=["summer", "cotton"],
                images=["front.jpg"],
                meta_title="Classic Cotton T-Shirt",
                meta_description="Shop our classic cotton T-shirt",
                handle="classic-t-shirt",
                status="draft",
                variants=[
                    ProductVariant(
                        tenant_id=TENANT_A,
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
            tenant_id=TENANT_A,
            email="admin@example.com",
            password_hash="unused",
        )
        with TenantSession(
            bind=engine, expire_on_commit=False, tenant_id=TENANT_A
        ) as session:
            yield RequestContext(
                tenant_id=TENANT_A,
                actor=admin.email,
                admin=admin,
                session=session,
            )

    app = FastAPI()
    app.include_router(products_router, prefix="/api/v1")
    app.include_router(reviews_router, prefix="/api/v1")
    app.dependency_overrides[get_request_context] = request_context
    return TestClient(app), engine


def test_generate_endpoint_creates_a_pending_task_and_dispatches() -> None:
    client, _ = make_client()
    product_id = client.get("/api/v1/products").json()[0]["id"]

    with patch("app.api.products.execute_task") as mock_execute:
        response = client.post(f"/api/v1/products/{product_id}/generate")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["risk_level"] == "medium"
    assert body["product_id"] == product_id
    assert set(body["changed_fields"]) == {
        "title",
        "description",
        "meta_title",
        "meta_description",
        "alt_text",
        "seo_tags",
    }
    mock_execute.delay.assert_called_once()


def test_generate_endpoint_rejects_an_unknown_product() -> None:
    client, _ = make_client()
    missing = "00000000-0000-0000-0000-00000000abcd"
    response = client.post(f"/api/v1/products/{missing}/generate")
    assert response.status_code == 404


def test_generate_workflow_and_review_queue_end_to_end() -> None:
    client, engine = make_client()
    product_id = client.get("/api/v1/products").json()[0]["id"]

    with patch("app.api.products.execute_task"):
        response = client.post(f"/api/v1/products/{product_id}/generate")
    task_id = response.json()["id"]

    assert client.get("/api/v1/reviews/queue").json() == []

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_A
    ) as session:
        status = run_task_workflow(session, UUID(task_id))
        session.commit()
    assert status == "awaiting_review"

    queue = client.get("/api/v1/reviews/queue")
    assert queue.status_code == 200
    items = queue.json()
    assert len(items) == 1
    assert items[0]["product_id"] == product_id
    assert items[0]["task_id"] == task_id
    assert items[0]["risk_level"] == "medium"
    assert items[0]["status"] == "pending_review"
    assert items[0]["title"] == "Classic T-Shirt"
