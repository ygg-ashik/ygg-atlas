"""Breakdown masking in the atlas kernel (D3.8): applied once in AtlasTools,
per label class, clearance and admin-set mode; every gap suppresses."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.atlas import AtlasCaller, AtlasRegistry, AtlasTools
from app.atlas.models import EntityDef, MetricDef
from app.models.audit import AtlasAuditLog
from tests.fakes import FakeMaskMode, StaticPolicy, make_tools

NAMES = ["Aisha Khan", "Omar Haddad", "Lina Saab"]
ROWS = [{"label": n, "value": v} for n, v in zip(NAMES, (30, 20, 10), strict=True)]
WEEK = {"start_date": "2026-01-01", "end_date": "2026-01-07"}
UNCLEARED: frozenset[str] = frozenset()


class _Connector:
    async def fetch_one(self, query: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"value": 1}

    async def fetch_all(
        self, query: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return [dict(r) for r in ROWS]


@pytest.fixture(autouse=True)
def _connector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.atlas.tools.get_connector", lambda _source: _Connector())


def _registry(label_class: str | None = "person_name") -> AtlasRegistry:
    metric = MetricDef(
        id="orders_by_rep",
        name="Orders by rep",
        entity="e",
        source="x",
        query="q",
        breakdown_query="b",
        breakdown_label_class=label_class,
    )
    entity = EntityDef(id="e", name="E", source="x", metrics=[metric])
    registry = AtlasRegistry(plugins={})
    registry.entities = {"e": entity}
    registry.metrics = {"orders_by_rep": metric}
    return registry


async def _breakdown(tools: AtlasTools) -> dict[str, Any]:
    result = await tools.execute(
        "metric_breakdown", {"metric_id": "orders_by_rep", **WEEK}
    )
    assert "error" not in result, result
    return result


def _assert_no_names(result: dict[str, Any]) -> None:
    for name in NAMES:
        assert name not in repr(result)


async def test_uncleared_suppress_returns_no_rows() -> None:
    tools = make_tools(
        registry=_registry(),
        clearances=UNCLEARED,
        modes={"person_name": ("suppress", 5)},
    )
    result = await _breakdown(tools)
    assert result["rows"] == []
    assert result["suppressed_rows"] == 3
    assert result["provenance"][0]["masking"] == {
        "label_class": "person_name",
        "mode": "suppress",
    }
    _assert_no_names(result)


async def test_uncleared_pseudonymise_hides_names() -> None:
    tools = make_tools(
        registry=_registry(),
        clearances=UNCLEARED,
        modes={"person_name": ("pseudonymise", 5)},
    )
    result = await _breakdown(tools)
    labels = [r["label"] for r in result["rows"]]
    assert all(label.startswith("Person ") for label in labels)
    assert len(set(labels)) == 3
    assert [r["value"] for r in result["rows"]] == [30.0, 20.0, 10.0]
    assert result["provenance"][0]["masking"] == {
        "label_class": "person_name",
        "mode": "pseudonymise",
    }
    _assert_no_names(result)


async def test_uncleared_bucket_names_top_rows_and_others() -> None:
    tools = make_tools(
        registry=_registry(),
        clearances=UNCLEARED,
        modes={"person_name": ("bucket", 1)},
    )
    result = await _breakdown(tools)
    assert result["rows"] == [
        {"label": "Top 1", "value": 30.0},
        {"label": "Others", "value": 30.0},
    ]
    assert result["others_covers"] == "remaining fetched rows"
    _assert_no_names(result)


async def test_a_cleared_caller_sees_names() -> None:
    tools = make_tools(
        registry=_registry(),
        clearances=frozenset({"fields:people_names"}),
        modes={"person_name": ("suppress", 5)},
    )
    result = await _breakdown(tools)
    assert [r["label"] for r in result["rows"]] == NAMES
    assert result["provenance"][0]["masking"] is None
    assert "suppressed_rows" not in result


async def test_the_wrong_clearance_does_not_unmask() -> None:
    tools = make_tools(
        registry=_registry(),
        clearances=frozenset({"fields:business_names"}),
        modes={"person_name": ("suppress", 5)},
    )
    assert (await _breakdown(tools))["rows"] == []


async def test_category_labels_are_never_masked() -> None:
    tools = make_tools(registry=_registry("category"), clearances=UNCLEARED)
    result = await _breakdown(tools)
    assert [r["label"] for r in result["rows"]] == NAMES
    assert result["provenance"][0]["masking"] is None


async def test_a_missing_mode_suppresses() -> None:
    tools = make_tools(registry=_registry(), clearances=UNCLEARED)
    result = await _breakdown(tools)
    assert result["rows"] == []
    assert result["suppressed_rows"] == 3


async def test_an_empty_key_suppresses_instead_of_pseudonymising() -> None:
    tools = make_tools(
        registry=_registry(),
        clearances=UNCLEARED,
        modes={"person_name": ("pseudonymise", 5)},
        pseudonym_key="",
    )
    result = await _breakdown(tools)
    assert result["rows"] == []
    assert result["provenance"][0]["masking"]["mode"] == "suppress"


async def test_a_metric_without_a_label_class_suppresses() -> None:
    tools = make_tools(registry=_registry(None), clearances=None)
    assert (await _breakdown(tools))["rows"] == []


class _RaisingClearancePolicy(StaticPolicy):
    def has_clearance(self, clearance: str) -> bool:
        raise RuntimeError("clearance store unreachable")


async def test_a_failing_clearance_check_suppresses() -> None:
    policy = _RaisingClearancePolicy(modes={"person_name": ("pseudonymise", 5)})
    tools = AtlasTools(
        AtlasCaller(user_id=uuid4(), auth_method="test"),
        policy,
        registry=_registry(),
        pseudonym_key="k",
    )
    result = await _breakdown(tools)
    assert result["rows"] == []
    assert result["suppressed_rows"] == 3


async def _audit_rows(db: AsyncSession, user_id: UUID) -> list[AtlasAuditLog]:
    result = await db.execute(
        select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == user_id)
    )
    return list(result.scalars().all())


async def test_audit_records_masking_without_label_values(db: AsyncSession) -> None:
    user_id = uuid4()
    tools = make_tools(
        db=db,
        registry=_registry(),
        clearances=UNCLEARED,
        modes={"person_name": ("bucket", 2)},
        user_id=user_id,
    )
    await _breakdown(tools)
    [row] = await _audit_rows(db, user_id)
    assert row.masking == {
        "label_class": "person_name",
        "mode": "bucket",
        "rows_in": 3,
        "rows_out": 3,
    }
    assert row.scope == {"restricted": False}
    for name in NAMES:
        assert name not in repr(row.masking)


@dataclass(frozen=True)
class _BrokenMode:
    mode: object
    bucket_size: object


@dataclass(frozen=True)
class _BrokenModePolicy(StaticPolicy):
    broken: _BrokenMode = _BrokenMode("bucket", True)

    def mask_mode(self, label_class: str) -> FakeMaskMode | None:
        return self.broken  # pyright: ignore[reportReturnType]  # a broken policy


@pytest.mark.parametrize(
    "broken",
    [_BrokenMode("bucket", True), _BrokenMode(None, 5), _BrokenMode("bucket", "5")],
)
async def test_a_malformed_mode_suppresses(broken: _BrokenMode) -> None:
    tools = AtlasTools(
        AtlasCaller(user_id=uuid4(), auth_method="test"),
        _BrokenModePolicy(clearances=UNCLEARED, broken=broken),
        registry=_registry(),
        pseudonym_key="k",
    )
    with capture_logs() as logs:
        result = await _breakdown(tools)
    assert result["rows"] == []
    assert result["suppressed_rows"] == 3
    [event] = [e for e in logs if e["event"] == "atlas.mask_mode_malformed"]
    assert event["log_level"] == "warning"
    assert set(event) == {"event", "log_level", "label_class"}  # no values
    assert event["label_class"] == "person_name"


@dataclass(frozen=True)
class _Settings:
    atlas_pseudonym_key: str


async def test_the_key_is_read_from_settings_at_mask_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = AtlasTools(
        AtlasCaller(user_id=uuid4(), auth_method="test"),
        StaticPolicy(
            clearances=UNCLEARED,
            modes=MappingProxyType({"person_name": ("pseudonymise", 5)}),
        ),
        registry=_registry(),
    )  # pseudonym_key=None: read lazily from settings
    monkeypatch.setattr("app.atlas.tools.get_settings", lambda: _Settings("k1"))
    first = [r["label"] for r in (await _breakdown(tools))["rows"]]
    monkeypatch.setattr("app.atlas.tools.get_settings", lambda: _Settings("k2"))
    second = [r["label"] for r in (await _breakdown(tools))["rows"]]
    assert all(label.startswith("Person ") for label in first + second)
    assert first != second  # the key is not cached at construction
    monkeypatch.setattr("app.atlas.tools.get_settings", lambda: _Settings(""))
    assert (await _breakdown(tools))["rows"] == []
