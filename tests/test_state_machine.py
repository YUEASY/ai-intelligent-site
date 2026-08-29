import pytest

from app.domain.task_state import InvalidTaskTransition, TaskState, transition

LEGAL_TRANSITIONS = {
    (TaskState.PENDING, TaskState.RUNNING),
    (TaskState.RUNNING, TaskState.AWAITING_REVIEW),
    (TaskState.RUNNING, TaskState.SUGGESTED),
    (TaskState.RUNNING, TaskState.PUBLISHED),
    (TaskState.RUNNING, TaskState.FAILED),
    (TaskState.SUGGESTED, TaskState.PUBLISHED),
    (TaskState.SUGGESTED, TaskState.FAILED),
    (TaskState.AWAITING_REVIEW, TaskState.APPROVED),
    (TaskState.AWAITING_REVIEW, TaskState.REJECTED),
    (TaskState.APPROVED, TaskState.PUBLISHED),
    (TaskState.PUBLISHED, TaskState.ROLLED_BACK),
}

ALL_TRANSITIONS = {
    (current, target)
    for current in TaskState
    for target in TaskState
    if current != target
}


@pytest.mark.parametrize(("current", "target"), sorted(LEGAL_TRANSITIONS))
def test_task_can_follow_every_legal_transition(
    current: TaskState, target: TaskState
) -> None:
    assert transition(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"), sorted(ALL_TRANSITIONS - LEGAL_TRANSITIONS)
)
def test_task_rejects_every_illegal_transition(
    current: TaskState, target: TaskState
) -> None:
    with pytest.raises(
        InvalidTaskTransition,
        match=f"Cannot transition task from {current.value} to {target.value}",
    ):
        transition(current, target)


@pytest.mark.parametrize("state", list(TaskState))
def test_task_rejects_transitioning_to_the_same_state(state: TaskState) -> None:
    with pytest.raises(InvalidTaskTransition):
        transition(state, state)
