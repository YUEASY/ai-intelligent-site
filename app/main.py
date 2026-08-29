from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from redis import Redis
from sqlalchemy import text

from app.api.auth import router as auth_router
from app.api.pages import router as pages_router
from app.api.products import router as products_router
from app.api.reviews import router as reviews_router
from app.api.shopify import router as shopify_router
from app.api.tasks import router as tasks_router
from app.bootstrap import ensure_bootstrap_admin, ensure_bootstrap_demo_data
from app.config import get_settings
from app.database import InfrastructureSessionFactory

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    ensure_bootstrap_admin(settings)
    ensure_bootstrap_demo_data(settings)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
app.include_router(pages_router, prefix="/api/v1")
app.include_router(reviews_router, prefix="/api/v1")
app.include_router(shopify_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    try:
        with InfrastructureSessionFactory() as session:
            session.execute(text("SELECT 1"))
        redis_client = Redis.from_url(settings.redis_url)
        try:
            redis_client.ping()
        finally:
            redis_client.close()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A required dependency is unavailable",
        ) from exc
    return {"status": "healthy"}
