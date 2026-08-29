from enum import StrEnum


class AlertKind(StrEnum):
    """The four alert categories the operator console surfaces.

    Each kind is raised from a deterministic code path — never by LLM
    self-assessment — and maps to one acceptance criterion of the observability
    milestone.
    """

    TASK_FAILED = "task_failed"
    DEAD_LETTER = "dead_letter"
    COST_THRESHOLD = "cost_threshold"
    WORKER_HEALTH = "worker_health"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
