"""Operator-facing alerts raised from deterministic code paths.

Alerts are deduplicated by an optional ``dedup_key`` while still open, so a
repeated failure or a re-checked threshold does not flood the operator console.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.database import TenantSession
from app.domain.alert import AlertKind, AlertStatus
from app.models import Alert


class AlertNotFoundError(LookupError):
    pass


class AlertService:
    def __init__(self, session: TenantSession) -> None:
        self._session = session

    def raise_alert(
        self,
        kind: AlertKind,
        message: str,
        *,
        dedup_key: str | None = None,
        task_id: UUID | None = None,
    ) -> Alert:
        if dedup_key is not None:
            existing = self._session.scalar(
                select(Alert).where(
                    Alert.kind == kind.value,
                    Alert.dedup_key == dedup_key,
                    Alert.status == AlertStatus.OPEN.value,
                )
            )
            if existing is not None:
                return existing
        alert = Alert(
            tenant_id=self._session.tenant_id,
            kind=kind.value,
            status=AlertStatus.OPEN.value,
            message=message[:2000],
            task_id=task_id,
            dedup_key=dedup_key,
        )
        self._session.add(alert)
        self._session.flush()
        return alert

    def list_alerts(self) -> list[Alert]:
        statement = select(Alert).order_by(Alert.created_at.desc(), Alert.id)
        return list(self._session.scalars(statement))

    def acknowledge(self, alert_id: UUID) -> Alert:
        alert = self._get(alert_id, for_update=True)
        if alert.status == AlertStatus.OPEN.value:
            alert.status = AlertStatus.ACKNOWLEDGED.value
            alert.acknowledged_at = datetime.now(UTC)
            self._session.flush()
        return alert

    def _get(self, alert_id: UUID, *, for_update: bool = False) -> Alert:
        statement = select(Alert).where(Alert.id == alert_id)
        if for_update:
            statement = statement.with_for_update()
        alert = self._session.scalar(statement)
        if alert is None:
            raise AlertNotFoundError(str(alert_id))
        return alert
