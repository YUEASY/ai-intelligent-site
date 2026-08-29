import csv
from io import StringIO

CSV_HEADERS = (
    "source",
    "source_id",
    "sku",
    "title",
    "description",
    "category",
    "tags",
    "images",
    "meta_title",
    "meta_description",
    "handle",
    "status",
    "variant_sku",
    "option1_name",
    "option1_value",
    "option2_name",
    "option2_value",
    "price",
    "cost",
    "inventory",
    "variant_image",
)


def canonical_row(**overrides: str) -> dict[str, str]:
    row = {
        "source": "merchant_csv",
        "source_id": "product-1",
        "sku": "TSHIRT",
        "title": "Classic T-Shirt",
        "description": "Heavy cotton tee",
        "category": "Apparel",
        "tags": "summer|cotton",
        "images": "front.jpg|back.jpg",
        "meta_title": "Classic Cotton T-Shirt",
        "meta_description": "Shop our classic cotton T-shirt",
        "handle": "classic-t-shirt",
        "status": "draft",
        "variant_sku": "TSHIRT-BLK-S",
        "option1_name": "Color",
        "option1_value": "Black",
        "option2_name": "Size",
        "option2_value": "S",
        "price": "29.90",
        "cost": "12.50",
        "inventory": "8",
        "variant_image": "black-small.jpg",
    }
    row.update(overrides)
    return row


def make_csv(
    *rows: dict[str, str], headers: tuple[str, ...] = CSV_HEADERS
) -> str:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
