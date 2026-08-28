import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from app.database import Base, TenantSession
from app.models import ShopifyOAuthState, ShopifyStore
from app.shopify.oauth import (
    SHOPIFY_OAUTH_SCOPES,
    EncryptedToken,
    InvalidOAuthCallback,
    ShopifyOAuthAdapter,
    ShopifyToken,
    SqlAlchemyOAuthStates,
    SqlAlchemyShopifyInstallations,
    TokenCipher,
)

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
CLIENT_SECRET = "oauth-client-secret"
ACCESS_TOKEN = "shpat_this_must_never_be_stored_in_plaintext"
ENCRYPTION_KEY = bytes(range(32))


class InMemoryOAuthStates:
    def __init__(self) -> None:
        self.saved: tuple[UUID, str, str, datetime] | None = None
        self.consumed = False

    def save(
        self,
        tenant_id: UUID,
        shop_domain: str,
        state_digest: str,
        expires_at: datetime,
    ) -> None:
        self.saved = (tenant_id, shop_domain, state_digest, expires_at)

    def consume(self, tenant_id: UUID, shop_domain: str, state_digest: str) -> bool:
        if self.saved is None or self.consumed:
            return False
        expected = self.saved[:3]
        if expected != (tenant_id, shop_domain, state_digest):
            return False
        self.consumed = True
        return True


class FakeTokenClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def exchange(self, shop_domain: str, code: str) -> ShopifyToken:
        self.calls.append((shop_domain, code))
        return ShopifyToken(
            access_token=ACCESS_TOKEN,
            granted_scopes=frozenset(SHOPIFY_OAUTH_SCOPES),
        )


@dataclass(frozen=True)
class StoredInstallation:
    tenant_id: UUID
    shop_domain: str
    token: EncryptedToken
    granted_scopes: frozenset[str]


class RecordingInstallations:
    def __init__(self) -> None:
        self.saved: StoredInstallation | None = None

    def connect(
        self,
        tenant_id: UUID,
        shop_domain: str,
        token: EncryptedToken,
        granted_scopes: frozenset[str],
    ) -> None:
        self.saved = StoredInstallation(
            tenant_id=tenant_id,
            shop_domain=shop_domain,
            token=token,
            granted_scopes=granted_scopes,
        )


def _callback_params(state: str) -> dict[str, str]:
    params = {
        "code": "one-time-code",
        "shop": "merchant.myshopify.com",
        "state": state,
        "timestamp": "1787932800",
    }
    message = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    params["hmac"] = hmac.new(
        CLIENT_SECRET.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return params


def _adapter(
    states: InMemoryOAuthStates,
    token_client: FakeTokenClient,
    installations: RecordingInstallations,
) -> ShopifyOAuthAdapter:
    return ShopifyOAuthAdapter(
        client_id="shopify-client-id",
        client_secret=CLIENT_SECRET,
        redirect_uri="https://platform.example.com/api/v1/shopify/oauth/callback",
        cipher=TokenCipher(ENCRYPTION_KEY),
        states=states,
        token_client=token_client,
        installations=installations,
    )


def test_oauth_requests_only_minimum_product_and_content_scopes() -> None:
    states = InMemoryOAuthStates()
    adapter = _adapter(states, FakeTokenClient(), RecordingInstallations())

    authorization_url = adapter.begin(
        tenant_id=TENANT_ID,
        shop_domain="merchant.myshopify.com",
    )

    parsed = urlparse(authorization_url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "merchant.myshopify.com"
    assert query["scope"] == ["write_products,write_content"]
    assert "orders" not in authorization_url
    assert "customers" not in authorization_url


def test_oauth_callback_encrypts_token_with_aes_gcm_before_storage() -> None:
    states = InMemoryOAuthStates()
    token_client = FakeTokenClient()
    installations = RecordingInstallations()
    adapter = _adapter(states, token_client, installations)
    authorization_url = adapter.begin(
        tenant_id=TENANT_ID,
        shop_domain="merchant.myshopify.com",
    )
    state = parse_qs(urlparse(authorization_url).query)["state"][0]

    result = adapter.complete(_callback_params(state))

    assert result.tenant_id == TENANT_ID
    assert result.shop_domain == "merchant.myshopify.com"
    assert token_client.calls == [("merchant.myshopify.com", "one-time-code")]
    stored = installations.saved
    assert stored is not None
    assert ACCESS_TOKEN.encode() not in stored.token.ciphertext
    assert (
        TokenCipher(ENCRYPTION_KEY).decrypt(
            stored.token,
            associated_data=f"{TENANT_ID}:merchant.myshopify.com".encode(),
        )
        == ACCESS_TOKEN
    )
    assert ACCESS_TOKEN not in repr(result)


def test_oauth_callback_rejects_bad_hmac_before_token_exchange() -> None:
    states = InMemoryOAuthStates()
    token_client = FakeTokenClient()
    installations = RecordingInstallations()
    adapter = _adapter(states, token_client, installations)
    authorization_url = adapter.begin(
        tenant_id=TENANT_ID,
        shop_domain="merchant.myshopify.com",
    )
    state = parse_qs(urlparse(authorization_url).query)["state"][0]
    params = _callback_params(state)
    params["hmac"] = "invalid"

    with pytest.raises(InvalidOAuthCallback, match="HMAC"):
        adapter.complete(params)

    assert states.consumed is False
    assert token_client.calls == []
    assert installations.saved is None


def test_oauth_database_contract_consumes_state_and_stores_only_ciphertext() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def session_factory(tenant_id: UUID) -> TenantSession:
        return TenantSession(bind=engine, expire_on_commit=False, tenant_id=tenant_id)

    cipher = TokenCipher(ENCRYPTION_KEY)
    adapter = ShopifyOAuthAdapter(
        client_id="shopify-client-id",
        client_secret=CLIENT_SECRET,
        redirect_uri="https://platform.example.com/api/v1/shopify/oauth/callback",
        cipher=cipher,
        states=SqlAlchemyOAuthStates(session_factory),
        token_client=FakeTokenClient(),
        installations=SqlAlchemyShopifyInstallations(session_factory),
    )
    authorization_url = adapter.begin(
        tenant_id=TENANT_ID,
        shop_domain="merchant.myshopify.com",
    )
    state = parse_qs(urlparse(authorization_url).query)["state"][0]

    adapter.complete(_callback_params(state))

    with session_factory(TENANT_ID) as session:
        oauth_state = session.scalar(select(ShopifyOAuthState))
        store = session.scalar(select(ShopifyStore))
        assert oauth_state is not None and oauth_state.consumed_at is not None
        assert store is not None
        assert store.encrypted_access_token is not None
        assert store.access_token_nonce is not None
        assert ACCESS_TOKEN.encode() not in store.encrypted_access_token
        assert (
            cipher.decrypt(
                EncryptedToken(
                    nonce=store.access_token_nonce,
                    ciphertext=store.encrypted_access_token,
                ),
                associated_data=f"{TENANT_ID}:merchant.myshopify.com".encode(),
            )
            == ACCESS_TOKEN
        )

    with pytest.raises(InvalidOAuthCallback, match="state"):
        adapter.complete(_callback_params(state))
