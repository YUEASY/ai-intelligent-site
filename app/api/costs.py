from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.cost_service import CostService
from app.dependencies import RequestContext, get_request_context
from app.schemas import CostOverviewRead, TaskCostRead

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("", response_model=CostOverviewRead)
def cost_overview(
    context: Annotated[RequestContext, Depends(get_request_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CostOverviewRead:
    service = CostService(context.session, settings)
    return CostOverviewRead(
        tenant_id=context.tenant_id,
        daily_cost=service.daily_cost(),
        daily_threshold=settings.alert_daily_cost_threshold_usd,
        total_cost=service.total_cost(),
        total_tokens=service.total_tokens(),
        tasks=[
            TaskCostRead.model_validate(row) for row in service.task_usages()
        ],
    )
