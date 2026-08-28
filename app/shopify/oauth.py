import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select

from app.database import TenantSession
from app.models import ShopifyOAuthState, ShopifyStore
from app.shopify.types import ShopifyStoreStatus

SHOPIFY_OAUTH_SCOPES = ("write_products", "write_content")
_SHOP_DOMAIN = re.compile(
    r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$",
    flags=re.IGNORECASE,
)


class InvalidOAuthCallback(ValueError):
    pass


class InvalidShopDomain(ValueError):
    pass


class OAuthScopeMismatch(ValueError):
    pass


class ShopifyTokenExchangeFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class EncryptedToken:
    nonce: bytes
    ciphertext: bytes


@dataclass(frozen=True)
class ShopifyToken:
    access_token: str
    granted_scopes: frozenset[str]


@dataclass(frozen=True)
class ConnectedShop:
    tenant_id: UUID
    shop_domain: str
    granted_scopes: frozenset[str]


class OAuthStates(Protocol):
    def save(
        self,
        tenant_id: UUID,
        shop_domain: str,
        state_digest: str,
        expires_at: datetime,
    ) -> None: ...

    def consume(
        self,
        tenant_id: UUID,
        shop_domain: str,
        state_digest: str,
    ) -> bool: ...


class OAuthTokenClient(Protocol):
    def exchange(self, shop_domain: str, code: str) -> ShopifyToken: ...


class HttpShopifyTokenClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 30,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout_seconds = timeout_seconds

    def exchange(self, shop_domain: str, code: str) -> ShopifyToken:
        request = Request(
            f"https://{shop_domain}/admin/oauth/access_token",
            data=urlencode(
                {
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                }
            ).encode(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.load(response)
            access_token = payload["access_token"]
            raw_scopes = payload["scope"]
            if not isinstance(access_token, str) or not isinstance(raw_scopes, str):
                raise TypeError
        except (
            HTTPError,
            URLError,
            TimeoutError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise ShopifyTokenExchangeFailed(
                "Shopify access-token exchange failed"
            ) from exc
        return ShopifyToken(
            access_token=access_token,
            granted_scopes=frozenset(
                scope.strip() for scope in raw_scopes.split(",") if scope.strip()
            ),
        )


class ShopifyInstallations(Protocol):
    def connect(
        self,
        tenant_id: UUID,
        shop_domain: str,
        token: EncryptedToken,
        granted_scopes: frozenset[str],
    ) -> None: ...


class TenantSessionFactory(Protocol):
    def __call__(self, tenant_id: UUID) -> TenantSession: ...


class SqlAlchemyOAuthStates:
    def __init__(self, session_factory: TenantSessionFactory) -> None:
        self._session_factory = session_factory

    def save(
        self,
        tenant_id: UUID,
        shop_domain: str,
        state_digest: str,
        expires_at: datetime,
    ) -> None:
        with self._session_factory(tenant_id) as session:
            session.add(
                ShopifyOAuthState(
                    tenant_id=tenant_id,
                    shop_domain=shop_domain,
                    state_digest=state_digest,
                    expires_at=expires_at,
                )
            )
            session.commit()

    def consume(
        self,
        tenant_id: UUID,
        shop_domain: str,
        state_digest: str,
    ) -> bool:
        with self._session_factory(tenant_id) as session:
            state = session.scalar(
                select(ShopifyOAuthState)
                .where(
                    ShopifyOAuthState.shop_domain == shop_domain,
                    ShopifyOAuthState.state_digest == state_digest,
                    ShopifyOAuthState.consumed_at.is_(None),
                    ShopifyOAuthState.expires_at > datetime.now(UTC),
                )
                .with_for_update()
            )
            if state is None:
                return False
            state.consumed_at = datetime.now(UTC)
            session.commit()
            return True


class SqlAlchemyShopifyInstallations:
    def __init__(self, session_factory: TenantSessionFactory) -> None:
        self._session_factory = session_factory

    def connect(
        self,
        tenant_id: UUID,
        shop_domain: str,
        token: EncryptedToken,
        granted_scopes: frozenset[str],
    ) -> None:
        with self._session_factory(tenant_id) as session:
            store = session.scalar(
                select(ShopifyStore)
                .where(ShopifyStore.shop_domain == shop_domain)
                .with_for_update()
            )
            if store is None:
                store = ShopifyStore(
                    tenant_id=tenant_id,
                    shop_domain=shop_domain,
                    granted_scopes=sorted(granted_scopes),
                )
                session.add(store)
            store.status = ShopifyStoreStatus.CONNECTED.value
            store.encrypted_access_token = token.ciphertext
            store.access_token_nonce = token.nonce
            store.granted_scopes = sorted(granted_scopes)
            store.connected_at = datetime.now(UTC)
            store.disconnected_at = None
            store.last_error = None
            session.commit()


class TokenCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Shopify token encryption key must contain 32 bytes")
        self._aes_gcm = AESGCM(key)

    def encrypt(self, plaintext: str, *, associated_data: bytes) -> EncryptedToken:
        nonce = secrets.token_bytes(12)
        ciphertext = self._aes_gcm.encrypt(
            nonce,
            plaintext.encode(),
            associated_data,
        )
        return EncryptedToken(nonce=nonce, ciphertext=ciphertext)

    def decrypt(self, token: EncryptedToken, *, associated_data: bytes) -> str:
        plaintext = self._aes_gcm.decrypt(
            token.nonce,
            token.ciphertext,
            associated_data,
        )
        return plaintext.decode()


class ShopifyOAuthAdapter:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        cipher: TokenCipher,
        states: OAuthStates,
        token_client: OAuthTokenClient,
        installations: ShopifyInstallations,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._cipher = cipher
        self._states = states
        self._token_client = token_client
        self._installations = installations

    def begin(self, *, tenant_id: UUID, shop_domain: str) -> str:
        shop_domain = normalize_shop_domain(shop_domain)
        state = f"{tenant_id}.{secrets.token_urlsafe(32)}"
        self._states.save(
            tenant_id,
            shop_domain,
            _state_digest(state),
            datetime.now(UTC) + timedelta(minutes=10),
        )
        query = urlencode(
            {
                "client_id": self._client_id,
                "scope": ",".join(SHOPIFY_OAUTH_SCOPES),
                "redirect_uri": self._redirect_uri,
                "state": state,
            }
        )
        return f"https://{shop_domain}/admin/oauth/authorize?{query}"

    def complete(self, params: Mapping[str, str]) -> ConnectedShop:
        self._verify_callback_hmac(params)
        shop_domain = normalize_shop_domain(_required_param(params, "shop"))
        state = _required_param(params, "state")
        tenant_id = _tenant_from_state(state)
        if not self._states.consume(
            tenant_id,
            shop_domain,
            _state_digest(state),
        ):
            raise InvalidOAuthCallback("Invalid or expired OAuth state")

        token = self._token_client.exchange(
            shop_domain,
            _required_param(params, "code"),
        )
        required_scopes = frozenset(SHOPIFY_OAUTH_SCOPES)
        if token.granted_scopes != required_scopes:
            raise OAuthScopeMismatch("Shopify granted unexpected access scopes")

        encrypted = self._cipher.encrypt(
            token.access_token,
            associated_data=_associated_data(tenant_id, shop_domain),
        )
        self._installations.connect(
            tenant_id,
            shop_domain,
            encrypted,
            token.granted_scopes,
        )
        return ConnectedShop(
            tenant_id=tenant_id,
            shop_domain=shop_domain,
            granted_scopes=token.granted_scopes,
        )

    def _verify_callback_hmac(self, params: Mapping[str, str]) -> None:
        supplied = params.get("hmac")
        message = "&".join(
            f"{key}={value}" for key, value in sorted(params.items()) if key != "hmac"
        )
        expected = hmac.new(
            self._client_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        if supplied is None or not hmac.compare_digest(expected, supplied):
            raise InvalidOAuthCallback("Invalid OAuth callback HMAC")


def normalize_shop_domain(shop_domain: str) -> str:
    normalized = shop_domain.strip().lower()
    if len(normalized) > 255 or _SHOP_DOMAIN.fullmatch(normalized) is None:
        raise InvalidShopDomain("Invalid Shopify shop domain")
    return normalized


def _required_param(params: Mapping[str, str], name: str) -> str:
    value = params.get(name)
    if not value:
        raise InvalidOAuthCallback(f"Missing OAuth callback parameter: {name}")
    return value


def _state_digest(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _tenant_from_state(state: str) -> UUID:
    tenant_value, separator, nonce = state.partition(".")
    if not separator or not nonce:
        raise InvalidOAuthCallback("Invalid OAuth state")
    try:
        return UUID(tenant_value)
    except ValueError as exc:
        raise InvalidOAuthCallback("Invalid OAuth state") from exc


def _associated_data(tenant_id: UUID, shop_domain: str) -> bytes:
    return f"{tenant_id}:{shop_domain}".encode()
