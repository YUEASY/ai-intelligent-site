from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.dependencies import RequestContext, get_request_context
from app.importing.csv_adapter import CsvImportAdapter, CsvImportValidationError
from app.product_service import ProductImportConflict, ProductService
from app.schemas import ProductImportRead, ProductRead

router = APIRouter(prefix="/products", tags=["products"])


@router.post(
    "/import", response_model=ProductImportRead, status_code=status.HTTP_201_CREATED
)
async def import_products(
    file: UploadFile,
    context: Annotated[RequestContext, Depends(get_request_context)],
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

    try:
        records = ProductService(context.session).import_products(canonical_products)
    except ProductImportConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    context.session.commit()
    product_reads = [ProductRead.model_validate(record) for record in records]
    return ProductImportRead(
        imported_products=len(product_reads),
        imported_variants=sum(len(product.variants) for product in product_reads),
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
