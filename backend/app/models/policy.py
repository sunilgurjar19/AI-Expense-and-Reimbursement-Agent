from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


# Categories that make a claim read as a business trip (used for titles and remarks).
TRAVEL_CATEGORIES = {"airfare", "rail_bus", "lodging", "travel_assistance"}


class CategoryRule(BaseModel):
    key: str
    label: str
    icon: str = "🧾"
    limit_per_item: float | None = None
    requires: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)  # words that rule this category out


class DuplicateRule(BaseModel):
    amount_tolerance: float = 1.0
    date_window_days: int = 2
    vendor_similarity: float = 0.75


class Policy(BaseModel):
    max_receipt_age_days: int = 90
    receipt_required_above: float = 300
    claim_requires_purpose: bool = True
    weekend_expenses: Literal["allow", "warn"] = "warn"
    duplicate_detection: DuplicateRule = DuplicateRule()
    required_fields: list[str] = Field(default_factory=list)
    blocked_keywords: list[str] = Field(default_factory=list)
    fx_rates: dict[str, float] = Field(default_factory=lambda: {"INR": 1})
    categories: list[CategoryRule] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Policy":
        with path.open(encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))

    def category(self, key: str | None) -> CategoryRule | None:
        return next((c for c in self.categories if c.key == key), None)
