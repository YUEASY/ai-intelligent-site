from uuid import UUID

import pytest

from app.importing.csv_adapter import CsvImportAdapter, CsvImportValidationError
from tests.csv_samples import CSV_HEADERS, canonical_row, make_csv

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_csv_is_normalized_into_a_canonical_product_with_variants() -> None:
    csv_content = make_csv(
        canonical_row(),
        canonical_row(
            variant_sku="TSHIRT-WHT-M",
            option1_value="White",
            option2_value="M",
            price="31.90",
            cost="13.00",
            inventory="5",
            variant_image="white-medium.jpg",
        ),
    )

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
            "alt_text": {},
            "handle": "classic-t-shirt",
            "status": "draft",
            "shopify_product_id": None,
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


def test_all_critical_fields_parse_for_at_least_95_percent_of_a_batch() -> None:
    rows = [
        canonical_row(
            source_id=f"product-{index}",
            sku=f"PRODUCT-{index}",
            title=f"Product {index}",
            handle=f"product-{index}",
            variant_sku=f"PRODUCT-{index}-VARIANT",
            images=f"https://images.example.com/{index}.jpg",
            variant_image=f"https://images.example.com/{index}-variant.jpg",
        )
        for index in range(20)
    ]

    products = CsvImportAdapter().parse(make_csv(*rows), tenant_id=TENANT_ID)

    assert len(products) / len(rows) >= 0.95
    assert all(
        product.source
        and product.source_id
        and product.sku
        and product.title
        and product.description
        and product.category
        and product.tags
        and product.images
        and product.meta_title
        and product.meta_description
        and product.handle
        and product.status
        and product.variants[0].sku
        and product.variants[0].options
        and product.variants[0].price >= 0
        and product.variants[0].cost is not None
        and product.variants[0].inventory >= 0
        and product.variants[0].image
        for product in products
    )


def test_invalid_rows_are_all_reported_with_line_numbers() -> None:
    csv_content = make_csv(
        canonical_row(title=""),
        canonical_row(
            source_id="product-2",
            sku="MUG",
            title="Mug",
            handle="mug",
            variant_sku="MUG-WHITE",
            price="not-a-price",
        ),
    )

    with pytest.raises(CsvImportValidationError) as captured:
        CsvImportAdapter().parse(csv_content, tenant_id=TENANT_ID)

    assert {error.line for error in captured.value.errors} == {2, 3}
    assert "title" in str(captured.value)
    assert "price" in str(captured.value)


def test_csv_rejects_more_than_two_variant_option_dimensions() -> None:
    headers = (*CSV_HEADERS[:17], "option3_name", "option3_value", *CSV_HEADERS[17:])
    csv_content = make_csv(
        canonical_row(option3_name="Fit", option3_value="Slim"), headers=headers
    )

    with pytest.raises(CsvImportValidationError) as captured:
        CsvImportAdapter().parse(csv_content, tenant_id=TENANT_ID)

    assert captured.value.errors[0].line == 2
    assert "at most 2 option dimensions" in str(captured.value)


def test_csv_rejects_conflicting_product_fields_across_variant_rows() -> None:
    csv_content = make_csv(
        canonical_row(),
        canonical_row(
            title="Different title",
            variant_sku="TSHIRT-WHT-M",
            option1_value="White",
            option2_value="M",
        ),
    )

    with pytest.raises(CsvImportValidationError) as captured:
        CsvImportAdapter().parse(csv_content, tenant_id=TENANT_ID)

    assert captured.value.errors[0].line == 3
    assert "conflicting product fields: title" in str(captured.value)


def test_empty_csv_is_rejected() -> None:
    with pytest.raises(CsvImportValidationError) as captured:
        CsvImportAdapter().parse(make_csv(), tenant_id=TENANT_ID)

    assert "CSV contains no product rows" in str(captured.value)


def test_csv_rejects_surplus_cells_in_a_row() -> None:
    csv_content = make_csv(canonical_row()).rstrip("\n") + ",unexpected\n"

    with pytest.raises(CsvImportValidationError) as captured:
        CsvImportAdapter().parse(csv_content, tenant_id=TENANT_ID)

    assert captured.value.errors[0].line == 2
    assert "unexpected extra columns" in str(captured.value)


def test_csv_rejects_a_blank_surplus_cell_in_a_row() -> None:
    csv_content = make_csv(canonical_row()).rstrip("\n") + ",\n"

    with pytest.raises(CsvImportValidationError) as captured:
        CsvImportAdapter().parse(csv_content, tenant_id=TENANT_ID)

    assert captured.value.errors[0].line == 2
    assert "unexpected extra columns" in str(captured.value)
