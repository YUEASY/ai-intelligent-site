from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, TenantSession
from app.domain.product import CanonicalProduct, CanonicalVariant, ProductStatus
from app.models import ShopifyStore
from app.shopify.oauth import TokenCipher, _associated_data
from app.shopify.products import (
    HttpShopifyProductClient,
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
        return {
            "product": {
                "id": int(remote_id),
                "images": [{"id": 987, "src": "shopify-front.jpg"}],
            }
        }

    def update_product_image(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        remote_product_id: str,
        remote_image_id: str,
        alt: str,
    ) -> dict[str, object]:
        self.calls.append(
            (
                "update_image",
                remote_image_id,
                {"product_id": remote_product_id, "alt": alt},
            )
        )
        if self._fail:
            raise ShopifyWriteError("storefront unavailable")
        return {"image": {"id": int(remote_image_id), "alt": alt}}


def test_http_client_accepts_shopify_image_update_receipt() -> None:
    response = BytesIO(b'{"image":{"id":987,"alt":"Optimized alt text"}}')
    with patch("app.shopify.products.urlopen", return_value=response):
        body = HttpShopifyProductClient().update_product_image(
            "merchant.myshopify.com",
            "test-token",
            "2026-07",
            "12345",
            "987",
            "Optimized alt text",
        )

    assert body["image"]["id"] == 987


def test_payload_maps_canonical_fields_to_shopify() -> None:
    payload = to_shopify_product_payload(make_product())
    product = payload["product"]
    assert product["title"] == "Classic T-Shirt"
    assert product["handle"] == "classic-t-shirt"
    assert product["status"] == "active"
    assert product["variants"][0]["sku"] == "TSHIRT-BLK"
    assert product["variants"][0]["price"] == "29.90"
    assert "compare_at_price" not in product["variants"][0]
    assert "metafields_title_tag" not in product
    assert "metafields_description_tag" not in product
    assert product["metafields"] == [
        {
            "namespace": "global",
            "key": "title_tag",
            "value": "Classic T-Shirt",
            "type": "single_line_text_field",
        },
        {
            "namespace": "global",
            "key": "description_tag",
            "value": "Shop our tee",
            "type": "multi_line_text_field",
        },
    ]


def test_payload_maps_image_alt_text() -> None:
    product = make_product()
    product.alt_text = {"front.jpg": "Classic T-Shirt Apparel"}
    payload = to_shopify_product_payload(product)
    assert payload["product"]["images"] == [
        {"src": "front.jpg", "alt": "Classic T-Shirt Apparel"}
    ]


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


def test_update_targets_existing_shopify_image_id_for_alt_text() -> None:
    client = FakeShopifyProductClient()
    adapter = ShopifyPlatformAdapter(
        shop_domain="merchant.myshopify.com",
        access_token="shpat_token",
        api_version="2026-07",
        client=client,
    )
    product = make_product(remote_id="12345")
    product.alt_text = {"front.jpg": "Optimized alt text"}

    receipt = adapter.update_product(TENANT_ID, product)

    assert receipt.success is True
    assert client.calls[0][0] == "update"
    assert "images" not in client.calls[0][2]["product"]
    assert client.calls[1] == (
        "update_image",
        "987",
        {"product_id": "12345", "alt": "Optimized alt text"},
    )


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
