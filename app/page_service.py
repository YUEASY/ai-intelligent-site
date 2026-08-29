from uuid import UUID

from sqlalchemy import select

from app.database import TenantSession
from app.models import Page


class PageNotFoundError(LookupError):
    pass


class PageService:
    def __init__(self, session: TenantSession) -> None:
        self._session = session

    def get(self, page_id: UUID) -> Page:
        page = self._session.scalar(select(Page).where(Page.id == page_id))
        if page is None:
            raise PageNotFoundError(str(page_id))
        return page

    def list_pages(self) -> list[Page]:
        return list(
            self._session.scalars(select(Page).order_by(Page.created_at.desc()))
        )
