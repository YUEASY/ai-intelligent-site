"""Version snapshot and field-diff helpers for products.

A snapshot captures the full publishable state of a product immediately before
a state-changing operation (publish or rollback) runs, together with the
field-level diff that the operation is about to apply.  Because the payload is
the pre-change state, it is exactly the state a later rollback restores, which
is why a snapshot is recorded *before* the change lands on the storefront.
"""

from enum import StrEnum
from typing import Any


class SnapshotKind(StrEnum):
    PUBLISH = "publish"
    ROLLBACK = "rollback"


def product_state(product: Any) -> dict[str, Any]:
    """Serialize a ``Product`` ORM row into a JSON-safe, diffable dict."""
    return {
        "title": product.title,
        "description": product.description,
        "category": product.category,
        "tags": list(product.tags),
        "images": list(product.images),
        "meta_title": product.meta_title,
        "meta_description": product.meta_description,
        "alt_text": dict(product.alt_text),
        "handle": product.handle,
        "status": product.status,
        "variants": [
            {
                "sku": variant.sku,
                "options": dict(variant.options),
                "price": str(variant.price),
                "cost": str(variant.cost) if variant.cost is not None else None,
                "inventory": variant.inventory,
                "image": variant.image,
            }
            for variant in product.variants
        ],
    }


def apply_draft_to_state(state: dict[str, Any], draft: Any) -> dict[str, Any]:
    """Overlay a draft's content fields onto a serialized product state."""
    result = dict(state)
    result["title"] = draft.title
    result["description"] = draft.description
    result["meta_title"] = draft.meta_title
    result["meta_description"] = draft.meta_description
    result["alt_text"] = dict(draft.alt_text)
    result["tags"] = list(draft.seo_tags)
    return result


def diff_states(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Return ``{field: {"from": old, "to": new}}`` for changed fields.

    Nested structures (variant lists) are compared as opaque JSON values, so a
    variant price change surfaces as a single ``variants`` entry.
    """

    fields = sorted(set(before) | set(after))
    return {
        field: {"from": before.get(field), "to": after.get(field)}
        for field in fields
        if before.get(field) != after.get(field)
    }
