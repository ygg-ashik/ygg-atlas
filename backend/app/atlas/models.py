"""Typed definitions for the atlas semantic registry.

Every metric/funnel is a vetted, parameterized query authored by a human.
The agent can only choose WHICH definition to run and for WHAT date range —
never the SQL itself.
"""

from pydantic import BaseModel, ConfigDict, Field


class MetricDef(BaseModel):
    id: str
    name: str
    description: str = ""
    entity: str = ""  # filled by registry loader
    source: str = ""  # filled by registry loader (the owning plugin id)
    unit: str = ""
    # 'range' queries use :start/:end (UTC bounds); 'snapshot' queries answer
    # "as of now" and take no date parameters.
    time_scope: str = "range"  # 'range' | 'snapshot'
    query: str
    # Optional top-N view: must return label/value rows and use :limit
    # (plus :start/:end when time_scope is 'range').
    breakdown_query: str | None = None
    # What the breakdown's labels are, for masking: 'category' (never masked),
    # 'business_name' or 'person_name'. Required whenever breakdown_query is set.
    breakdown_label_class: str | None = None
    good_direction: str = "up"  # 'up' | 'down' — how to read changes


class FunnelStepDef(BaseModel):
    id: str
    name: str
    query: str  # parameterized with :start and :end, returns a single count


class FunnelDef(BaseModel):
    id: str
    name: str
    description: str = ""
    entity: str = ""
    source: str = ""
    steps: list[FunnelStepDef]


class ScopeDimensionDef(BaseModel):
    """One row-scope dimension an entity can be restricted on.

    `column` is the SQL column text a grant's values are matched against (linted
    at load; grant values are always bind parameters). `self` (YAML key) names the
    user attribute that `$self` resolves to for this dimension.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    column: str
    self_attribute: str | None = Field(default=None, alias="self")
    description: str = ""


class EntityDef(BaseModel):
    id: str
    name: str
    description: str = ""
    source: str = ""  # filled by registry loader (the owning plugin id)
    pii_fields: list[str] = Field(default_factory=list)
    fields: dict[str, str] = Field(default_factory=dict)  # field name -> description
    freshness_query: str | None = None  # returns single timestamp of newest data
    metrics: list[MetricDef] = Field(default_factory=list)
    funnels: list[FunnelDef] = Field(default_factory=list)
    # Dimension name -> definition. When set, every query of the entity must
    # carry the {{scope}} placeholder (registry lint).
    scope_dimensions: dict[str, ScopeDimensionDef] = Field(default_factory=dict)
