from decimal import Decimal
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, TenantSession
from app.domain.product import CanonicalProduct, CanonicalVariant, ProductStatus
from app.models import ShopifyStore
from app.shopify.oauth import TokenCipher, _associated_data
from app.shopify.products import (
    ShopifyPlatformAdapter,
    ShopifyPlatformAdapterFactory,
    ShopifyWriteError,
    to_shopify_product_payload,
)
from app.shopify.types import ShopifyStoreStatus

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_product(*, remote_id: str | None = None) -> CanonicalProduct:
    return CanonicalProduct(
        tenant_id=TENANT_ID,
        source="merchant_csv",
        source_id="product-1",
        sku="TSHIRT",
        title="Classic T-Shirt",
        description="Heavy cotton tee",
        category="Apparel",
        tags=["summer", "cotton"],
        images=["front.jpg"],
        meta_title="Classic T-Shirt",
        meta_description="Shop our tee",
        handle="classic-t-shirt",
        status=ProductStatus.ACTIVE,
        shopify_product_id=remote_id,
        variants=[
            CanonicalVariant(
                sku="TSHIRT-BLK",
                options={"Color": "Black"},
                price=Decimal("29.90"),
                cost=Decimal("12.50"),
                inventory=8,
                image=None,
            )
        ],
    )


class FakeShopifyProductClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self._fail = fail

    def create_product(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append(("create", shop_domain, payload))
        if self._fail:
            raise ShopifyWriteError("storefront unavailable")
        return {"product": {"id": 12345}}

    def update_product(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        remote_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append(("update", remote_id, payload))
        if self._fail:
            raise ShopifyWriteError("storefront unavailable")
        return {"product": {"id": int(remote_id)}}


def test_payload_maps_canonical_fields_to_shopify() -> None:
    payload = to_shopify_product_payload(make_product())
    product = payload["product"]
    assert product["title"] == "Classic T-Shirt"
    assert product["handle"] == "classic-t-shirt"
    assert product["status"] == "active"
    assert product["variants"][0]["sku"] == "TSHIRT-BLK"
    assert product["variants"][0]["price"] == "29.90"


def test_publish_returns_success_receipt_with_remote_id() -> None:
    client = FakeShopifyProductClient()
    adapter = ShopifyPlatformAdapter(
        shop_domain="merchant.myshopify.com",
        access_token="shpat_token",
        api_version="2026-07",
        client=client,
    )

    receipt = adapter.publish_product(TENANT_ID, make_product())

    assert receipt.success is True
    assert receipt.remote_id == "12345"
    assert client.calls[0][0] == "create"


def test_publish_returns_failed_receipt_when_shopify_fails() -> None:
    client = FakeShopifyProductClient(fail=True)
    adapter = ShopifyPlatformAdapter(
        shop_domain="merchant.myshopify.com",
        access_token="shpat_token",
        api_version="2026-07",
        client=client,
    )

    receipt = adapter.publish_product(TENANT_ID, make_product())

    assert receipt.success is False
    assert receipt.remote_id is None


def test_update_without_remote_id_fails() -> None:
    adapter = ShopifyPlatformAdapter(
        shop_domain="merchant.myshopify.com",
        access_token="shpat_token",
        api_version="2026-07",
        client=FakeShopifyProductClient(),
    )

    receipt = adapter.update_product(TENANT_ID, make_product(remote_id=None))

    assert receipt.success is False


def test_factory_decrypts_token_and_builds_store_adapter() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def session_factory(tenant_id: UUID) -> TenantSession:
        return TenantSession(bind=engine, expire_on_commit=False, tenant_id=tenant_id)

    cipher = TokenCipher(bytes(range(32)))
    shop_domain = "merchant.myshopify.com"
    encrypted = cipher.encrypt(
        "shpat_secret", associated_data=_associated_data(TENANT_ID, shop_domain)
    )
    with session_factory(TENANT_ID) as session:
        session.add(
            ShopifyStore(
                tenant_id=TENANT_ID,
                shop_domain=shop_domain,
                status=ShopifyStoreStatus.CONNECTED.value,
                encrypted_access_token=encrypted.ciphertext,
                access_token_nonce=encrypted.nonce,
                granted_scopes=["write_products", "write_content"],
            )
        )
        session.commit()

    client = FakeShopifyProductClient()
    factory = ShopifyPlatformAdapterFactory(
        session_factory=session_factory, cipher=cipher, client=client
    )
    adapter = factory(TENANT_ID)

    receipt = adapter.publish_product(TENANT_ID, make_product())
    assert receipt.success is True
    assert client.calls[0][1] == shop_domain
