from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import RequestContext, get_request_context
from app.generation.service import DraftService
from app.schemas import DraftRead

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("/queue", response_model=list[DraftRead])
def review_queue(
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[DraftRead]:
    return [
        DraftRead.model_validate(draft)
        for draft in DraftService(context.session).review_queue()
    ]
