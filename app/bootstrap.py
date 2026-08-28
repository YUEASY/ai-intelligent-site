from sqlalchemy import select

from app.auth import hash_password
from app.config import Settings
from app.database import InfrastructureSessionFactory
from app.models import AdminUser


def ensure_bootstrap_admin(settings: Settings) -> None:
    with InfrastructureSessionFactory.begin() as session:
        existing = session.scalar(
            select(AdminUser).where(
                AdminUser.tenant_id == settings.bootstrap_tenant_id,
                AdminUser.email == settings.bootstrap_admin_email,
            )
        )
        if existing is not None:
            return
        session.add(
            AdminUser(
                tenant_id=settings.bootstrap_tenant_id,
                email=settings.bootstrap_admin_email,
                password_hash=hash_password(
                    settings.bootstrap_admin_password.get_secret_value()
                ),
            )
        )
