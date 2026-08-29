from enum import StrEnum


class DraftStatus(StrEnum):
    """Lifecycle of an AI-generated draft.

    Only `pending_review` is produced by the generation stage; approve / reject /
    publish transitions are exercised by the review workflow.
    """

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
