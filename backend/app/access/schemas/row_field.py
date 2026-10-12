"""Row and field controls: user attributes, label classes, scope dimensions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.access.facts import MAX_ATTRIBUTE_VALUE, MAX_BUCKET_SIZE


class AttributePut(BaseModel):
    value: str = Field(min_length=1, max_length=MAX_ATTRIBUTE_VALUE)


class LabelClassPut(BaseModel):
    mode: Literal["pseudonymise", "suppress", "bucket"]
    bucket_size: int | None = Field(default=None, ge=1, le=MAX_BUCKET_SIZE)


class AttributeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    set_by: UUID | None
    set_at: datetime


class LabelClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label_class: str
    mode: str
    bucket_size: int
    updated_at: datetime


class ScopeDimensionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    entity: str
    dimension: str
    self_attribute: str | None
    description: str
