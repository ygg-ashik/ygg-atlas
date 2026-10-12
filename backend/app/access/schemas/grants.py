"""Grants: the create payload (with its row-scope validation) and the row shape."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.access.facts import (
    MAX_ATTRIBUTE_VALUE,
    MAX_SCOPE_DIMENSIONS,
    MAX_SCOPE_VALUES,
    SCOPE_KEY,
    is_well_formed_scope,
)


class GrantCreate(BaseModel):
    subject_type: Literal["group", "user"]
    subject_id: UUID
    effect: Literal["allow", "deny"] = "allow"
    target_kind: Literal["resource", "capability", "clearance"] = "resource"
    target: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=500)
    expires_at: AwareDatetime | None = None
    # None = all rows; else {dimension: [values]}, `$self` allowed.
    row_scope: dict[str, list[str]] | None = None

    @field_validator("row_scope")
    @classmethod
    def _normalized_scope(
        cls, scope: dict[str, list[str]] | None
    ) -> dict[str, list[str]] | None:
        return None if scope is None else _normalize_scope(scope)


def _normalize_scope(scope: dict[str, list[str]]) -> dict[str, list[str]]:
    """Validate a row scope and return it with sorted keys and de-duplicated,
    sorted values. Never returns a scope the evaluator would treat as
    malformed: `is_well_formed_scope` is the final word."""
    if not 1 <= len(scope) <= MAX_SCOPE_DIMENSIONS:
        msg = f"A row scope names 1 to {MAX_SCOPE_DIMENSIONS} dimensions."
        raise ValueError(msg)
    normalized: dict[str, list[str]] = {}
    for key in sorted(scope):
        values = [v.strip() for v in scope[key]]
        if not SCOPE_KEY.fullmatch(key):
            msg = (
                f"'{key}' is not a scope dimension name: up to 64 lowercase "
                "letters, digits and underscores, starting with a letter."
            )
            raise ValueError(msg)
        if not 1 <= len(values) <= MAX_SCOPE_VALUES:
            msg = f"Scope '{key}' needs 1 to {MAX_SCOPE_VALUES} values."
            raise ValueError(msg)
        if any(not 1 <= len(v) <= MAX_ATTRIBUTE_VALUE for v in values):
            msg = (
                f"Each value of scope '{key}' is 1 to {MAX_ATTRIBUTE_VALUE} characters."
            )
            raise ValueError(msg)
        normalized[key] = sorted(set(values))
    if not is_well_formed_scope(normalized):
        msg = "That row scope is not valid."
        raise ValueError(msg)
    return normalized


class GrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject_type: str
    subject_id: UUID
    effect: str
    target_kind: str
    target: str
    reason: str
    expires_at: datetime | None
    created_by: UUID | None
    created_at: datetime
    row_scope: dict[str, list[str]] | None = None
