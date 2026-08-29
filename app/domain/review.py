from enum import StrEnum


class RejectionReason(StrEnum):
    """Structured reason a reviewer rejects a draft.

    The canonical set comes from the parent spec: fact error, expression, SEO,
    brand style, and a catch-all for anything else.  Feed these back into
    prompt/rule refinement instead of free-text so rejections stay comparable.
    """

    FACT_ERROR = "fact_error"
    EXPRESSION = "expression"
    SEO = "seo"
    BRAND_STYLE = "brand_style"
    OTHER = "other"
