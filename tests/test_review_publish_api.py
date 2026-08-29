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
from app.domain.task_state import TaskState
from app.models import AdminUser, Product, ProductDraft, ProductVariant, Task
from app.platform import RecordingPlatformAdapter

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_client() -> tuple[TestClient, Engine, RecordingPlatformAdapter]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session:
        product = Product(
            tenant_id=TENANT_ID,
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
        session.add(product)
        session.flush()
        task = Task(
            tenant_id=TENANT_ID,
            kind="product",
            operation_type="update",
            changed_fields=["title", "description"],
            risk_level="medium",
            status=TaskState.AWAITING_REVIEW.value,
            product_id=product.id,
        )
        session.add(task)
        session.flush()
        session.add(
            ProductDraft(
                tenant_id=TENANT_ID,
                product_id=product.id,
                task_id=task.id,
                title="Edited Classic T-Shirt",
                description="Edited heavy cotton tee",
                meta_title="Edited meta title",
                meta_description="Edited meta description",
                alt_text={},
                seo_tags=["edited", "cotton"],
                risk_level="medium",
                status=DraftStatus.PENDING_REVIEW.value,
            )
        )
        session.commit()
        product_id = product.id

    admin = AdminUser(
        id=uuid4(),
        tenant_id=TENANT_ID,
        email="admin@example.com",
        password_hash="unused",
    )

    def request_context() -> Iterator[RequestContext]:
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
    app.include_router(reviews_router, prefix="/api/v1")
    app.include_router(products_router, prefix="/api/v1")
    app.dependency_overrides[get_request_context] = request_context
    app.dependency_overrides[get_platform_adapter_factory] = (
        override_adapter_factory
    )
    client = TestClient(app)
    return client, engine, adapter, product_id


def _draft_id(client: TestClient) -> str:
    queue = client.get("/api/v1/reviews/queue").json()
    return queue[0]["id"]


def test_approve_and_reject_endpoints_advance_drafts() -> None:
    client, _, _, _ = make_client()
    draft_id = _draft_id(client)

    approved = client.post(
        "/api/v1/reviews/approve", json={"draft_ids": [draft_id]}
    )
    assert approved.status_code == 200
    assert approved.json()[0]["status"] == "approved"

    rejected = client.post(
        "/api/v1/reviews/reject",
        json={"draft_ids": [draft_id], "reason": "fact_error"},
    )
    assert rejected.status_code == 409  # already approved, not reviewable


def test_edit_and_regenerate_endpoints() -> None:
    client, _, _, _ = make_client()
    draft_id = _draft_id(client)

    edited = client.patch(
        f"/api/v1/reviews/{draft_id}",
        json={"title": "Fixed Title"},
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "Fixed Title"

    with patch("app.api.reviews.execute_task") as mock_execute:
        regenerated = client.post(
            f"/api/v1/reviews/{draft_id}/regenerate"
        )
    assert regenerated.status_code == 202
    assert regenerated.json()["status"] == "pending"
    mock_execute.delay.assert_called_once()


def test_publish_requires_confirmation() -> None:
    client, _, _, _ = make_client()
    draft_id = _draft_id(client)

    response = client.post(
        f"/api/v1/reviews/{draft_id}/publish", json={"confirmed": False}
    )
    assert response.status_code == 409


def test_publish_writes_to_shopify_and_records_version() -> None:
    client, engine, adapter, product_id = make_client()
    draft_id = _draft_id(client)
    approved = client.post(
        "/api/v1/reviews/approve", json={"draft_ids": [draft_id]}
    )
    assert approved.status_code == 200

    response = client.post(
        f"/api/v1/reviews/{draft_id}/publish", json={"confirmed": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["remote_id"] == "remote-1"
    assert body["draft"]["status"] == "published"
    assert body["task"]["status"] == "published"
    assert body["snapshot"]["version"] == 1
    assert adapter.write_calls[0][0] == "publish_product"

    versions = client.get(f"/api/v1/products/{product_id}/versions")
    assert versions.status_code == 200
    assert [version["version"] for version in versions.json()] == [1]

    rollback = client.post(
        f"/api/v1/products/{product_id}/rollback", json={"version": 1}
    )
    assert rollback.status_code == 200
    assert rollback.json()["task"]["status"] == "rolled_back"
    assert rollback.json()["snapshot"]["restored_version"] == 1
    assert adapter.write_calls[1][0] == "update_product"
