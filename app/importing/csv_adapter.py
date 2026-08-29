import csv
import re
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from io import StringIO
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CSV_HEADERS = frozenset(
    {
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
    }
)
PRODUCT_FIELDS = (
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
)


@dataclass(frozen=True)
class CsvRowError:
    line: int
    message: str


class CsvImportValidationError(ValueError):
    def __init__(self, errors: list[CsvRowError]) -> None:
        self.errors = tuple(errors)
        message = "; ".join(
            f"line {error.line}: {error.message}" for error in self.errors
        )
        super().__init__(message)


class CanonicalVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=255)
    options: dict[str, str]
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    cost: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    inventory: int = Field(ge=0, le=2_147_483_647)
    image: str | None = Field(default=None, max_length=2048)


class CanonicalProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    source: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)
    sku: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    description: str
    category: str
    tags: list[str]
    images: list[str]
    meta_title: str = Field(max_length=255)
    meta_description: str
    handle: str = Field(min_length=1, max_length=255)
    status: Literal["draft", "active", "archived"]
    variants: list[CanonicalVariant] = Field(min_length=1)


class CsvImportAdapter:
    """Normalize a merchant CSV into canonical products."""

    def parse(self, content: str, *, tenant_id: UUID) -> list[CanonicalProduct]:
        rows = csv.DictReader(StringIO(content.removeprefix("\ufeff")))
        missing_headers = CSV_HEADERS.difference(rows.fieldnames or ())
        if missing_headers:
            missing = ", ".join(sorted(missing_headers))
            raise CsvImportValidationError(
                [CsvRowError(line=1, message=f"missing required columns: {missing}")]
            )

        grouped: OrderedDict[tuple[str, str], CanonicalProduct] = OrderedDict()
        errors: list[CsvRowError] = []
        row_count = 0

        for line, row in enumerate(rows, start=2):
            row_count += 1
            try:
                parsed = _parse_row(row, tenant_id)
            except ValidationError as exc:
                errors.extend(
                    CsvRowError(
                        line=line,
                        message=f"{'.'.join(str(part) for part in error['loc'])}: "
                        f"{error['msg']}",
                    )
                    for error in exc.errors()
                )
                continue
            except ValueError as exc:
                errors.append(CsvRowError(line=line, message=str(exc)))
                continue

            source = parsed.source
            source_id = parsed.source_id
            key = (source, source_id)
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = parsed
            else:
                conflicting_fields = [
                    field
                    for field in PRODUCT_FIELDS
                    if getattr(existing, field) != getattr(parsed, field)
                ]
                if conflicting_fields:
                    errors.append(
                        CsvRowError(
                            line=line,
                            message="conflicting product fields: "
                            + ", ".join(conflicting_fields),
                        )
                    )
                    continue
                existing.variants.extend(parsed.variants)

        if row_count == 0:
            errors.append(CsvRowError(line=1, message="CSV contains no product rows"))
        if errors:
            raise CsvImportValidationError(errors)
        return list(grouped.values())


def _parse_row(row: dict[str, str | None], tenant_id: UUID) -> CanonicalProduct:
    def value(name: str) -> str:
        return (row.get(name) or "").strip()

    extra_option_columns = [
        name
        for name, raw_value in row.items()
        if name is not None
        and re.fullmatch(r"option([3-9]|[1-9][0-9]+)_(name|value)", name)
        and (raw_value or "").strip()
    ]
    if extra_option_columns:
        raise ValueError("variants support at most 2 option dimensions")

    option_pairs = [
        (value(f"option{index}_name"), value(f"option{index}_value"))
        for index in (1, 2)
    ]
    if any(bool(name) != bool(option_value) for name, option_value in option_pairs):
        raise ValueError("variant option name and value must be provided together")
    options = {name: option_value for name, option_value in option_pairs if name}
    if len(options) != sum(1 for name, _ in option_pairs if name):
        raise ValueError("variant option names must be unique")
    return CanonicalProduct.model_validate(
        {
            "tenant_id": tenant_id,
            "source": value("source"),
            "source_id": value("source_id"),
            "sku": value("sku"),
            "title": value("title"),
            "description": value("description"),
            "category": value("category"),
            "tags": _split_values(value("tags")),
            "images": _split_values(value("images")),
            "meta_title": value("meta_title"),
            "meta_description": value("meta_description"),
            "handle": value("handle"),
            "status": value("status"),
            "variants": [
                {
                    "sku": value("variant_sku"),
                    "options": options,
                    "price": value("price"),
                    "cost": value("cost") or None,
                    "inventory": value("inventory"),
                    "image": value("variant_image") or None,
                }
            ],
        }
    )


def _split_values(value: str) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()]
