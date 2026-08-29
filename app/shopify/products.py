"""Store-backed Shopify Platform Adapter.

The Platform Adapter seam writes canonical products to Shopify and returns a
receipt only when Shopify actually acknowledged the write.  This module wires
the seam to the real Admin REST API: it decrypts the tenant's stored access
token and maps a canonical product onto Shopify's product JSON.
"""

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from sqlalchemy import select

from app.database import TenantSession
from app.domain.page import CanonicalPage
from app.domain.product import CanonicalProduct, ProductStatus
from app.models import ShopifyStore
from app.platform import PlatformReceipt
from app.shopify.oauth import EncryptedToken, TokenCipher, _associated_data
from app.shopify.types import ShopifyStoreStatus

DEFAULT_API_VERSION = "2026-07"


class NoConnectedShopifyStore(LookupError):
    pass


class ShopifyWriteError(RuntimeError):
    pass


def to_shopify_product_payload(
    product: CanonicalProduct, *, include_images: bool = True
) -> dict[str, object]:
    """Map a canonical product onto Shopify's product create/update JSON."""
    product_payload: dict[str, object] = {
        "title": product.title,
        "body_html": product.description,
        "product_type": product.category,
        "tags": ",".join(product.tags),
        "handle": product.handle,
        "status": ("active" if product.status is ProductStatus.ACTIVE else "draft"),
        "metafields": [
            {
                "namespace": "global",
                "key": "title_tag",
                "value": product.meta_title,
                "type": "single_line_text_field",
            },
            {
                "namespace": "global",
                "key": "description_tag",
                "value": product.meta_description,
                "type": "multi_line_text_field",
            },
        ],
        "variants": [
            {
                "sku": variant.sku,
                "price": str(variant.price),
                "inventory_quantity": variant.inventory,
                "option1": _option_values(variant.options, 0),
                "option2": _option_values(variant.options, 1),
            }
            for variant in product.variants
        ],
    }
    if include_images:
        product_payload["images"] = [
            {"src": image, "alt": product.alt_text.get(image, "")}
            for image in product.images
        ]
    return {"product": product_payload}


def _option_values(options: dict[str, str], index: int) -> str:
    values = list(options.values())
    return values[index] if index < len(values) else ""


class ShopifyProductClient(Protocol):
    def create_product(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        payload: dict[str, object],
    ) -> dict[str, Any]: ...

    def update_product(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        remote_id: str,
        payload: dict[str, object],
    ) -> dict[str, Any]: ...

    def update_product_image(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        remote_product_id: str,
        remote_image_id: str,
        alt: str,
    ) -> dict[str, Any]: ...

    def update_page(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        remote_id: str,
        payload: dict[str, object],
    ) -> dict[str, Any]: ...


class HttpShopifyProductClient:
    def __init__(self, *, timeout_seconds: float = 30) -> None:
        self._timeout_seconds = timeout_seconds

    def create_product(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        payload: dict[str, object],
    ) -> dict[str, Any]:
        return self._request(
            shop_domain=shop_domain,
            access_token=access_token,
            api_version=api_version,
            path="products.json",
            method="POST",
            payload=payload,
            expected_resource="product",
        )

    def update_product(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        remote_id: str,
        payload: dict[str, object],
    ) -> dict[str, Any]:
        return self._request(
            shop_domain=shop_domain,
            access_token=access_token,
            api_version=api_version,
            path=f"products/{remote_id}.json",
            method="PUT",
            payload=payload,
            expected_resource="product",
        )

    def update_product_image(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        remote_product_id: str,
        remote_image_id: str,
        alt: str,
    ) -> dict[str, Any]:
        return self._request(
            shop_domain=shop_domain,
            access_token=access_token,
            api_version=api_version,
            path=f"products/{remote_product_id}/images/{remote_image_id}.json",
            method="PUT",
            payload={"image": {"id": remote_image_id, "alt": alt}},
            expected_resource="image",
        )

    def update_page(
        self,
        shop_domain: str,
        access_token: str,
        api_version: str,
        remote_id: str,
        payload: dict[str, object],
    ) -> dict[str, Any]:
        return self._request(
            shop_domain=shop_domain,
            access_token=access_token,
            api_version=api_version,
            path=f"pages/{remote_id}.json",
            method="PUT",
            payload=payload,
            expected_resource="page",
        )

    def _request(
        self,
        *,
        shop_domain: str,
        access_token: str,
        api_version: str,
        path: str,
        method: str,
        payload: dict[str, object],
        expected_resource: str,
    ) -> dict[str, Any]:
        request = Request(
            f"https://{shop_domain}/admin/api/{api_version}/{path}",
            data=json.dumps(payload).encode(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": access_token,
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                body = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ShopifyWriteError("Shopify product write failed") from exc
        if not isinstance(body, dict) or expected_resource not in body:
            raise ShopifyWriteError("Shopify returned an unexpected response")
        return body


class ShopifyPlatformAdapter:
    """Write canonical products to a single merchant storefront."""

    def __init__(
        self,
        *,
        shop_domain: str,
        access_token: str,
        api_version: str,
        client: ShopifyProductClient,
    ) -> None:
        self._shop_domain = shop_domain
        self._access_token = access_token
        self._api_version = api_version
        self._client = client

    def publish_product(
        self, tenant_id: UUID, product: CanonicalProduct
    ) -> PlatformReceipt:
        del tenant_id
        try:
            body = self._client.create_product(
                self._shop_domain,
                self._access_token,
                self._api_version,
                to_shopify_product_payload(product),
            )
            return PlatformReceipt.ok(remote_id=str(body["product"]["id"]))
        except (ShopifyWriteError, KeyError, TypeError) as exc:
            return PlatformReceipt.failed(str(exc))

    def update_product(
        self, tenant_id: UUID, product: CanonicalProduct
    ) -> PlatformReceipt:
        del tenant_id
        if product.shopify_product_id is None:
            return PlatformReceipt.failed("product has no Shopify id to update")
        try:
            body = self._client.update_product(
                self._shop_domain,
                self._access_token,
                self._api_version,
                product.shopify_product_id,
                to_shopify_product_payload(product, include_images=False),
            )
            self._update_image_alt_text(product, body)
            return PlatformReceipt.ok(remote_id=str(body["product"]["id"]))
        except (ShopifyWriteError, KeyError, TypeError) as exc:
            return PlatformReceipt.failed(str(exc))

    def _update_image_alt_text(
        self, product: CanonicalProduct, response: dict[str, Any]
    ) -> None:
        if not product.alt_text:
            return
        remote_images = response["product"].get("images", [])
        if not isinstance(remote_images, list):
            raise ShopifyWriteError("Shopify returned invalid product images")
        for position, image_url in enumerate(product.images):
            alt = product.alt_text.get(image_url)
            if alt is None:
                continue
            remote_image = next(
                (
                    image
                    for image in remote_images
                    if isinstance(image, dict) and image.get("src") == image_url
                ),
                remote_images[position] if position < len(remote_images) else None,
            )
            if not isinstance(remote_image, dict) or "id" not in remote_image:
                raise ShopifyWriteError(f"Shopify image id missing for {image_url}")
            self._client.update_product_image(
                self._shop_domain,
                self._access_token,
                self._api_version,
                product.shopify_product_id or "",
                str(remote_image["id"]),
                alt,
            )

    def update_page(self, tenant_id: UUID, page: CanonicalPage) -> PlatformReceipt:
        del tenant_id
        try:
            body = self._client.update_page(
                self._shop_domain,
                self._access_token,
                self._api_version,
                page.shopify_page_id,
                {
                    "page": {
                        "id": page.shopify_page_id,
                        "title": page.title,
                        "body_html": page.body_html,
                        "handle": page.handle,
                        "metafields": [
                            {
                                "namespace": "global",
                                "key": "title_tag",
                                "value": page.meta_title,
                                "type": "single_line_text_field",
                            },
                            {
                                "namespace": "global",
                                "key": "description_tag",
                                "value": page.meta_description,
                                "type": "multi_line_text_field",
                            },
                            {
                                "namespace": "seo",
                                "key": "tags",
                                "value": ",".join(page.seo_tags),
                                "type": "single_line_text_field",
                            },
                        ],
                    }
                },
            )
            return PlatformReceipt.ok(str(body["page"]["id"]))
        except (ShopifyWriteError, KeyError, TypeError) as exc:
            return PlatformReceipt.failed(str(exc))


class ShopifyPlatformAdapterFactory:
    """Build a store-backed adapter for a tenant, decrypting its access token."""

    def __init__(
        self,
        *,
        session_factory: "CallableSessionFactory",
        cipher: TokenCipher,
        api_version: str = DEFAULT_API_VERSION,
        client: ShopifyProductClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        self._api_version = api_version
        self._client = client or HttpShopifyProductClient()

    def __call__(self, tenant_id: UUID) -> ShopifyPlatformAdapter:
        with self._session_factory(tenant_id) as session:
            store = session.scalar(
                select(ShopifyStore).where(
                    ShopifyStore.status == ShopifyStoreStatus.CONNECTED.value
                )
            )
            if store is None:
                raise NoConnectedShopifyStore(
                    f"No connected Shopify store for tenant {tenant_id}"
                )
            shop_domain = store.shop_domain
            access_token = self._cipher.decrypt(
                EncryptedToken(
                    nonce=store.access_token_nonce or b"",
                    ciphertext=store.encrypted_access_token or b"",
                ),
                associated_data=_associated_data(tenant_id, shop_domain),
            )
        return ShopifyPlatformAdapter(
            shop_domain=shop_domain,
            access_token=access_token,
            api_version=self._api_version,
            client=self._client,
        )


class CallableSessionFactory(Protocol):
    def __call__(self, tenant_id: UUID) -> TenantSession: ...
