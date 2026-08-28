from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI 智能建站"
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/ai_site"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: SecretStr = SecretStr(
        "development-only-change-this-secret-before-production"
    )
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 480
    bootstrap_tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: SecretStr = SecretStr("change-me")
    shopify_client_id: str = "development-shopify-client-id"
    shopify_client_secret: SecretStr = SecretStr("development-shopify-client-secret")
    shopify_redirect_uri: str = "http://localhost:8000/api/v1/shopify/oauth/callback"
    shopify_token_encryption_key: SecretStr = SecretStr(
        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
    )

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> "Settings":
        if self.environment == "production" and (
            self.jwt_secret.get_secret_value().startswith("development-only")
            or self.bootstrap_admin_password.get_secret_value() == "change-me"
            or self.shopify_client_id.startswith("development-")
            or self.shopify_client_secret.get_secret_value().startswith("development-")
            or self.shopify_token_encryption_key.get_secret_value()
            == "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
        ):
            raise ValueError("Production secrets must be explicitly configured")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
