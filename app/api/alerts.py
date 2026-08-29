from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.alert_service import AlertNotFoundError, AlertService
from app.dependencies import RequestContext, get_request_context
from app.schemas import AlertRead

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertRead])
def list_alerts(
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[AlertRead]:
    return [
        AlertRead.model_validate(alert)
        for alert in AlertService(context.session).list_alerts()
    ]


@router.post("/{alert_id}/acknowledge", response_model=AlertRead)
def acknowledge_alert(
    alert_id: UUID,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> AlertRead:
    try:
        alert = AlertService(context.session).acknowledge(alert_id)
    except AlertNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Alert not found") from exc
    return AlertRead.model_validate(alert)
