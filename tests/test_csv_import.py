# ruff: noqa: E501

from uuid import UUID

import pytest

from app.importing.csv_adapter import CsvImportAdapter, CsvImportValidationError

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_csv_is_normalized_into_a_canonical_product_with_variants() -> None:
    csv_content = """source,source_id,sku,title,description,category,tags,images,meta_title,meta_description,handle,status,variant_sku,option1_name,option1_value,option2_name,option2_value,price,cost,inventory,variant_image
merchant_csv,product-1,TSHIRT,Classic T-Shirt,Heavy cotton tee,Apparel,summer|cotton,front.jpg|back.jpg,Classic Cotton T-Shirt,Shop our classic cotton T-shirt,classic-t-shirt,draft,TSHIRT-BLK-S,Color,Black,Size,S,29.90,12.50,8,black-small.jpg
merchant_csv,product-1,TSHIRT,Classic T-Shirt,Heavy cotton tee,Apparel,summer|cotton,front.jpg|back.jpg,Classic Cotton T-Shirt,Shop our classic cotton T-shirt,classic-t-shirt,draft,TSHIRT-WHT-M,Color,White,Size,M,31.90,13.00,5,white-medium.jpg
"""

    products = CsvImportAdapter().parse(csv_content, tenant_id=TENANT_ID)

    assert [product.model_dump(mode="json") for product in products] == [
        {
            "tenant_id": str(TENANT_ID),
            "source": "merchant_csv",
            "source_id": "product-1",
            "sku": "TSHIRT",
            "title": "Classic T-Shirt",
            "description": "Heavy cotton tee",
            "category": "Apparel",
            "tags": ["summer", "cotton"],
            "images": ["front.jpg", "back.jpg"],
            "meta_title": "Classic Cotton T-Shirt",
            "meta_description": "Shop our classic cotton T-shirt",
            "handle": "classic-t-shirt",
            "status": "draft",
            "variants": [
                {
                    "sku": "TSHIRT-BLK-S",
                    "options": {"Color": "Black", "Size": "S"},
                    "price": "29.90",
                    "cost": "12.50",
                    "inventory": 8,
                    "image": "black-small.jpg",
                },
                {
                    "sku": "TSHIRT-WHT-M",
                    "options": {"Color": "White", "Size": "M"},
                    "price": "31.90",
                    "cost": "13.00",
                    "inventory": 5,
                    "image": "white-medium.jpg",
                },
            ],
        }
    ]


def test_invalid_rows_are_all_reported_with_line_numbers() -> None:
    csv_content = """source,source_id,sku,title,description,category,tags,images,meta_title,meta_description,handle,status,variant_sku,option1_name,option1_value,option2_name,option2_value,price,cost,inventory,variant_image
merchant_csv,product-1,TSHIRT,,Heavy cotton tee,Apparel,summer,front.jpg,Meta,Description,classic-t-shirt,draft,TSHIRT-S,Size,S,,,29.90,12.50,8,small.jpg
merchant_csv,product-2,MUG,Mug,Ceramic mug,Home,gift,mug.jpg,Mug,Description,mug,draft,MUG-WHITE,Color,White,,,not-a-price,3.00,12,mug-white.jpg
"""

    with pytest.raises(CsvImportValidationError) as captured:
        CsvImportAdapter().parse(csv_content, tenant_id=TENANT_ID)

    assert {error.line for error in captured.value.errors} == {2, 3}
    assert "title" in str(captured.value)
    assert "price" in str(captured.value)


def test_csv_rejects_more_than_two_variant_option_dimensions() -> None:
    csv_content = """source,source_id,sku,title,description,category,tags,images,meta_title,meta_description,handle,status,variant_sku,option1_name,option1_value,option2_name,option2_value,option3_name,option3_value,price,cost,inventory,variant_image
merchant_csv,product-1,SHIRT,Shirt,Cotton shirt,Apparel,summer,front.jpg,Shirt,Description,shirt,draft,SHIRT-BLK-S-SLIM,Color,Black,Size,S,Fit,Slim,29.90,12.50,8,black-small.jpg
"""

    with pytest.raises(CsvImportValidationError) as captured:
        CsvImportAdapter().parse(csv_content, tenant_id=TENANT_ID)

    assert captured.value.errors[0].line == 2
    assert "at most 2 option dimensions" in str(captured.value)


def test_csv_rejects_conflicting_product_fields_across_variant_rows() -> None:
    csv_content = """source,source_id,sku,title,description,category,tags,images,meta_title,meta_description,handle,status,variant_sku,option1_name,option1_value,option2_name,option2_value,price,cost,inventory,variant_image
merchant_csv,product-1,SHIRT,Shirt,Cotton shirt,Apparel,summer,front.jpg,Shirt,Description,shirt,draft,SHIRT-S,Size,S,,,29.90,12.50,8,small.jpg
merchant_csv,product-1,SHIRT,Different title,Cotton shirt,Apparel,summer,front.jpg,Shirt,Description,shirt,draft,SHIRT-M,Size,M,,,29.90,12.50,8,medium.jpg
"""

    with pytest.raises(CsvImportValidationError) as captured:
        CsvImportAdapter().parse(csv_content, tenant_id=TENANT_ID)

    assert captured.value.errors[0].line == 3
    assert "conflicting product fields: title" in str(captured.value)


def test_empty_csv_is_rejected() -> None:
    header_only = """source,source_id,sku,title,description,category,tags,images,meta_title,meta_description,handle,status,variant_sku,option1_name,option1_value,option2_name,option2_value,price,cost,inventory,variant_image
"""

    with pytest.raises(CsvImportValidationError) as captured:
        CsvImportAdapter().parse(header_only, tenant_id=TENANT_ID)

    assert "CSV contains no product rows" in str(captured.value)
