# ruff: noqa: E501

from collections.abc import Iterator
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.products import router
from app.database import Base, TenantSession
from app.dependencies import RequestContext, get_request_context
from app.models import AdminUser

TENANT_A = UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = UUID("00000000-0000-0000-0000-000000000002")


def test_imported_products_are_listed_only_for_the_current_tenant() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    current_tenant = {"id": TENANT_A}

    def request_context() -> Iterator[RequestContext]:
        tenant_id = current_tenant["id"]
        admin = AdminUser(
            id=uuid4(),
            tenant_id=tenant_id,
            email="admin@example.com",
            password_hash="unused",
        )
        with TenantSession(
            bind=engine, expire_on_commit=False, tenant_id=tenant_id
        ) as session:
            yield RequestContext(
                tenant_id=tenant_id,
                actor=admin.email,
                admin=admin,
                session=session,
            )

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_request_context] = request_context
    client = TestClient(app)
    csv_content = """source,source_id,sku,title,description,category,tags,images,meta_title,meta_description,handle,status,variant_sku,option1_name,option1_value,option2_name,option2_value,price,cost,inventory,variant_image
merchant_csv,product-1,TSHIRT,Classic T-Shirt,Heavy cotton tee,Apparel,summer|cotton,front.jpg|back.jpg,Classic Cotton T-Shirt,Shop our classic cotton T-shirt,classic-t-shirt,draft,TSHIRT-BLK-S,Color,Black,Size,S,29.90,12.50,8,black-small.jpg
"""

    imported = client.post(
        "/api/v1/products/import",
        files={"file": ("products.csv", csv_content, "text/csv")},
    )

    assert imported.status_code == 201
    assert imported.json()["imported_products"] == 1
    products = client.get("/api/v1/products")
    assert products.status_code == 200
    assert products.json() == [
        {
            "id": products.json()[0]["id"],
            "tenant_id": str(TENANT_A),
            "source": "merchant_csv",
            "source_id": "product-1",
            "sku": "TSHIRT",
            "title": "Classic T-Shirt",
            "description": "Heavy cotton tee",
            "category": "Apparel",
            "tags": ["summer", "cotton"],
            "images": ["front.jpg", "back.jpg"],
            "meta_title": "Classic Cotton T-Shirt",
            "meta_description": "Shop our classic cotton T-shirt",
            "handle": "classic-t-shirt",
            "status": "draft",
            "variants": [
                {
                    "id": products.json()[0]["variants"][0]["id"],
                    "sku": "TSHIRT-BLK-S",
                    "options": {"Color": "Black", "Size": "S"},
                    "price": "29.90",
                    "cost": "12.50",
                    "inventory": 8,
                    "image": "black-small.jpg",
                }
            ],
        }
    ]

    duplicate = client.post(
        "/api/v1/products/import",
        files={"file": ("products.csv", csv_content, "text/csv")},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == (
        "Product merchant_csv/product-1 already exists for this tenant"
    )

    current_tenant["id"] = TENANT_B
    assert client.get("/api/v1/products").json() == []

    invalid_csv = csv_content.replace(
        ",Classic T-Shirt,Heavy cotton tee,", ",,Heavy cotton tee,"
    )
    invalid = client.post(
        "/api/v1/products/import",
        files={"file": ("invalid.csv", invalid_csv, "text/csv")},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"][0]["line"] == 2
    assert "title" in invalid.json()["detail"][0]["message"]
    assert client.get("/api/v1/products").json() == []
