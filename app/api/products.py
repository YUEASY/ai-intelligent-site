from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)

from app.api.platform_deps import (
    PlatformAdapterFactory,
    get_platform_adapter_factory,
)
from app.dependencies import RequestContext, get_request_context
from app.domain.risk import OperationType
from app.generation.workflow import ALL_CONTENT_FIELDS
from app.importing.csv_adapter import CsvImportAdapter, CsvImportValidationError
from app.product_service import (
    ProductImageNotFoundError,
    ProductImageUpload,
    ProductImportConflict,
    ProductImportValidationError,
    ProductNotFoundError,
    ProductService,
)
from app.publish_service import PublishFailed, PublishService
from app.schemas import (
    ProductImportRead,
    ProductRead,
    RollbackRead,
    RollbackRequest,
    SeoRequest,
    SnapshotRead,
    TaskCreate,
    TaskKind,
    TaskRead,
)
from app.seo import SEO_ALL_FIELDS, SEO_LOW_RISK_FIELDS, is_published
from app.services import TaskService
from app.shopify.products import NoConnectedShopifyStore
from app.snapshot_service import SnapshotNotFoundError, SnapshotService
from app.worker import execute_task

router = APIRouter(prefix="/products", tags=["products"])


@router.post(
    "/import", response_model=ProductImportRead, status_code=status.HTTP_201_CREATED
)
async def import_products(
    file: UploadFile,
    context: Annotated[RequestContext, Depends(get_request_context)],
    images: Annotated[list[UploadFile] | None, File()] = None,
) -> ProductImportRead:
    try:
        content = (await file.read()).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[{"line": 1, "message": "CSV must be UTF-8 encoded"}],
        ) from exc

    try:
        canonical_products = CsvImportAdapter().parse(
            content, tenant_id=context.tenant_id
        )
    except CsvImportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[
                {"line": error.line, "message": error.message}
                for error in exc.errors
            ],
        ) from exc

    image_uploads = [
        ProductImageUpload(
            filename=image.filename or "",
            content_type=image.content_type or "application/octet-stream",
            content=await image.read(),
        )
        for image in images or []
    ]
    try:
        records = ProductService(context.session).import_products(
            canonical_products, image_uploads
        )
    except ProductImportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except ProductImportConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    context.session.commit()
    product_reads = [ProductRead.model_validate(record) for record in records]
    return ProductImportRead(
        imported_products=len(product_reads),
        imported_variants=sum(len(product.variants) for product in product_reads),
        imported_images=sum(len(product.image_assets) for product in records),
        products=product_reads,
    )


@router.get("", response_model=list[ProductRead])
def list_products(
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[ProductRead]:
    return [
        ProductRead.model_validate(product)
        for product in ProductService(context.session).list_products()
    ]


@router.post(
    "/{product_id}/generate",
    response_model=TaskRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_product_content(
    product_id: UUID,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> TaskRead:
    try:
        ProductService(context.session).get(product_id)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    task = TaskService(context.session, actor=context.actor).create(
        TaskCreate(
            kind=TaskKind.PRODUCT,
            operation_type=OperationType.UPDATE,
            changed_fields=set(ALL_CONTENT_FIELDS),
            product_id=product_id,
        )
    )
    context.session.commit()
    execute_task.delay(str(task.id), str(task.tenant_id))
    return TaskRead.model_validate(task)


@router.post(
    "/{product_id}/seo",
    response_model=TaskRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def optimize_product_seo(
    product_id: UUID,
    command: SeoRequest,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> TaskRead:
    try:
        product = ProductService(context.session).get(product_id)
    except ProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        ) from exc
    if not is_published(product):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Product is not published yet",
        )

    fields = SEO_ALL_FIELDS if command.include_title else SEO_LOW_RISK_FIELDS
    task = TaskService(context.session, actor=context.actor).create(
        TaskCreate(
            kind=TaskKind.SEO,
            operation_type=OperationType.UPDATE,
            changed_fields=set(fields),
            product_id=product_id,
        )
    )
    context.session.commit()
    execute_task.delay(str(task.id), str(task.tenant_id))
    return TaskRead.model_validate(task)


@router.get("/{product_id}/versions", response_model=list[SnapshotRead])
def list_product_versions(
    product_id: UUID,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> list[SnapshotRead]:
    try:
        ProductService(context.session).get(product_id)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Product not found") from exc
    snapshots = SnapshotService(context.session).list_versions(product_id)
    return [SnapshotRead.model_validate(snapshot) for snapshot in snapshots]


@router.post("/{product_id}/rollback", response_model=RollbackRead)
def rollback_product(
    product_id: UUID,
    command: RollbackRequest,
    context: Annotated[RequestContext, Depends(get_request_context)],
    adapter_factory: Annotated[
        PlatformAdapterFactory, Depends(get_platform_adapter_factory)
    ],
) -> RollbackRead:
    try:
        adapter = adapter_factory(context.tenant_id)
    except NoConnectedShopifyStore as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shopify store is not connected",
        ) from exc
    try:
        result = PublishService(context.session, context.actor, adapter).rollback(
            product_id, command.version
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Product not found") from exc
    except SnapshotNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PublishFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Shopify did not confirm the rollback",
        ) from exc
    context.session.commit()
    return RollbackRead(
        product=ProductRead.model_validate(result.product),
        task=TaskRead.model_validate(result.task) if result.task else None,
        snapshot=SnapshotRead.model_validate(result.snapshot),
    )


@router.get("/{product_id}/images/{filename}")
def get_product_image(
    product_id: UUID,
    filename: str,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> Response:
    try:
        image = ProductService(context.session).get_image(product_id, filename)
    except ProductImageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    return Response(content=image.content, media_type=image.content_type)
