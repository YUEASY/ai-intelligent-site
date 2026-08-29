from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CanonicalPage:
    tenant_id: UUID
    title: str
    body_html: str
    handle: str
    meta_title: str
    meta_description: str
    seo_tags: list[str]
    shopify_page_id: str
