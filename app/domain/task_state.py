from enum import StrEnum


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUGGESTED = "suggested"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


LEGAL_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset({TaskState.RUNNING}),
    TaskState.RUNNING: frozenset(
        {
            TaskState.AWAITING_REVIEW,
            TaskState.SUGGESTED,
            TaskState.PUBLISHED,
            TaskState.FAILED,
        }
    ),
    TaskState.SUGGESTED: frozenset({TaskState.PUBLISHED, TaskState.FAILED}),
    TaskState.AWAITING_REVIEW: frozenset({TaskState.APPROVED, TaskState.REJECTED}),
    TaskState.APPROVED: frozenset({TaskState.PUBLISHED}),
    TaskState.PUBLISHED: frozenset({TaskState.ROLLED_BACK}),
    TaskState.REJECTED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.ROLLED_BACK: frozenset(),
}


class InvalidTaskTransition(ValueError):
    def __init__(self, current: TaskState, target: TaskState) -> None:
        super().__init__(
            f"Cannot transition task from {current.value} to {target.value}"
        )
        self.current = current
        self.target = target


def transition(current: TaskState, target: TaskState) -> TaskState:
    """Return the target state when the transition is legal."""
    if target not in LEGAL_TRANSITIONS[current]:
        raise InvalidTaskTransition(current, target)
    return target
