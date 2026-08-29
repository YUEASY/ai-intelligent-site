from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, TenantSession
from app.importing.csv_adapter import CsvImportAdapter
from app.product_service import ProductImportValidationError, ProductService
from tests.csv_samples import canonical_row, make_csv

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_business_service_rejects_a_third_variant_option_dimension() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    product = CsvImportAdapter().parse(
        make_csv(
            canonical_row(
                images="https://images.example.com/product.jpg",
                variant_image="https://images.example.com/variant.jpg",
            )
        ),
        tenant_id=TENANT_ID,
    )[0]
    product.variants[0].options["Fit"] = "Slim"

    with TenantSession(
        bind=engine, expire_on_commit=False, tenant_id=TENANT_ID
    ) as session, pytest.raises(ProductImportValidationError, match="at most 2"):
        ProductService(session).import_products([product])
