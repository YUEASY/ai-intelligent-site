from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import Uuid, create_engine, event
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
    with_loader_criteria,
)

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class TenantOwned:
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)


class TenantScopeViolation(ValueError):
    pass


class TenantSession(Session):
    """ORM session whose reads and writes are bound to exactly one tenant."""

    def __init__(self, *args: Any, tenant_id: UUID, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.tenant_id = tenant_id


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
InfrastructureSessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(TenantSession, "do_orm_execute")
def _enforce_tenant_filter(execute_state: Any) -> None:
    if not execute_state.is_orm_statement:
        return

    tenant_id = execute_state.session.tenant_id
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantOwned,
            lambda model: model.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


@event.listens_for(TenantSession, "before_flush")
def _enforce_tenant_writes(
    session: TenantSession, flush_context: Any, instances: Any
) -> None:
    del flush_context, instances
    for record in session.new.union(session.dirty):
        if not isinstance(record, TenantOwned):
            continue
        if record.tenant_id != session.tenant_id:
            raise TenantScopeViolation(
                f"Record tenant {record.tenant_id} does not match "
                f"session tenant {session.tenant_id}"
            )


@contextmanager
def tenant_session_scope(tenant_id: UUID) -> Iterator[TenantSession]:
    session = tenant_session(tenant_id)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def tenant_session(tenant_id: UUID) -> TenantSession:
    return TenantSession(bind=engine, expire_on_commit=False, tenant_id=tenant_id)


def infrastructure_session() -> Generator[Session, None, None]:
    """Unscoped session for health checks and application bootstrap only."""
    with InfrastructureSessionFactory() as session:
        yield session
