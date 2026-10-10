"""Offline tests for the golden-suite harness (evals/run_evals.py): no LLM, no DB."""

import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from app.access.catalog import CLEARANCE_PEOPLE_NAMES
from app.identity import User

_EVALS = Path(__file__).resolve().parents[2] / "evals"


def _load_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_evals", _EVALS / "run_evals.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = _load_harness()


def _user() -> User:
    return User(
        id=uuid4(),
        email=harness.EVAL_EMAIL,
        display_name="Eval runner",
        role="viewer",
    )


def test_plain_string_allow_is_unscoped() -> None:
    policy = harness._policy(_user(), {"allow": ["demo/order/*"]})
    assert policy.allows("demo/order/revenue")
    assert policy.row_scope("demo/order/revenue") is None
    assert not policy.allows("demo/funnel/checkout_funnel")


def test_default_allow_is_everything() -> None:
    policy = harness._policy(_user(), {})
    assert policy.allows("demo/order/revenue")
    assert policy.row_scope("demo/order/revenue") is None


def test_object_allow_carries_row_scope() -> None:
    golden = {"allow": [{"pattern": "demo/order/*", "row_scope": {"channel": ["b2c"]}}]}
    policy = harness._policy(_user(), golden)
    assert policy.row_scope("demo/order/revenue") == ({"channel": frozenset({"b2c"})},)


def test_self_scope_resolves_from_golden_attributes() -> None:
    golden = {
        "allow": [{"pattern": "demo/order/*", "row_scope": {"sales_rep": ["$self"]}}],
        "attributes": {"rep_name": "Aisha Khan"},
    }
    policy = harness._policy(_user(), golden)
    assert policy.row_scope("demo/order/orders_count") == (
        {"sales_rep": frozenset({"Aisha Khan"})},
    )


def test_self_scope_without_attribute_is_skipped() -> None:
    golden = {
        "allow": [{"pattern": "demo/order/*", "row_scope": {"sales_rep": ["$self"]}}]
    }
    policy = harness._policy(_user(), golden)
    assert not policy.allows("demo/order/orders_count")
    assert policy.skipped


def test_golden_cannot_override_builtin_attributes() -> None:
    user = _user()
    attributes = harness._attributes(user, {"attributes": {"email": "x@evil.com"}})
    assert attributes["email"] == harness.EVAL_EMAIL
    assert attributes["user_id"] == str(user.id)


def test_clearances_become_clearance_grants() -> None:
    policy = harness._policy(_user(), {"clearances": [CLEARANCE_PEOPLE_NAMES]})
    assert policy.has_clearance(CLEARANCE_PEOPLE_NAMES)
    assert not harness._policy(_user(), {}).has_clearance(CLEARANCE_PEOPLE_NAMES)


def test_label_modes_default_to_the_seeded_settings() -> None:
    policy = harness._policy(_user(), {})
    person = policy.mask_mode("person_name")
    business = policy.mask_mode("business_name")
    assert person is not None
    assert (person.mode, person.bucket_size) == ("suppress", 5)
    assert business is not None
    assert (business.mode, business.bucket_size) == ("pseudonymise", 5)


def test_label_modes_are_overridable() -> None:
    golden = {"label_modes": {"person_name": {"mode": "bucket", "bucket_size": 3}}}
    mode = harness._policy(_user(), golden).mask_mode("person_name")
    assert mode is not None
    assert (mode.mode, mode.bucket_size) == ("bucket", 3)


def test_malformed_allow_entry_is_rejected() -> None:
    with pytest.raises(ValueError, match="allow entry"):
        harness._policy(_user(), {"allow": [{"row_scope": {"channel": ["b2c"]}}]})


def test_check_none_fails_on_forbidden_text_case_insensitive() -> None:
    golden = {"expect_none": ["Aisha", "Omar"]}
    assert harness._check_none(golden, harness.Turn(answer="Top rep: AISHA khan"))
    assert not harness._check_none(golden, harness.Turn(answer="Rep names hidden"))
    assert not harness._check_none({}, harness.Turn(answer="Aisha"))
    assert harness._check_none in harness._CHECKS


def test_row_field_goldens_load_and_build_policies() -> None:
    goldens = {g["id"]: g for g in harness._load_goldens(None)}
    for golden_id in (
        "scoped-revenue-b2c",
        "masked-rep-breakdown",
        "self-scoped-rep",
        "undeclared-scope-is-honest",
    ):
        assert golden_id in goldens
        harness._policy(_user(), goldens[golden_id])  # builds without error
    scoped = harness._policy(_user(), goldens["self-scoped-rep"])
    assert scoped.row_scope("demo/order/orders_count") == (
        {"sales_rep": frozenset({"Aisha Khan"})},
    )
    masked = harness._policy(_user(), goldens["masked-rep-breakdown"])
    assert not masked.has_clearance(CLEARANCE_PEOPLE_NAMES)


def test_check_none_scans_blocks_and_provenance() -> None:
    golden = {"expect_none": ["Aisha"]}
    in_block = harness.Turn(
        answer="Here is the breakdown.",
        blocks=[{"kind": "artifact", "rows": [{"label": "Aisha Khan", "value": 21}]}],
    )
    assert harness._check_none(golden, in_block)
    in_provenance = harness.Turn(
        answer="Done.", provenance=[{"metric_id": "orders_by_rep", "note": "AISHA"}]
    )
    assert harness._check_none(golden, in_provenance)


@pytest.mark.parametrize(
    "row_scope",
    [["b2c"], {"channel": "b2c"}, {"channel": [1]}, {1: ["b2c"]}],
)
def test_malformed_row_scope_is_rejected(row_scope: object) -> None:
    golden = {"allow": [{"pattern": "demo/order/*", "row_scope": row_scope}]}
    with pytest.raises(ValueError, match="row_scope"):
        harness._policy(_user(), golden)


def test_conflicting_self_dimension_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Registry:
        def scope_catalog(self) -> list[tuple[str, str, str, str | None, str]]:
            return [
                ("a", "e1", "rep", "rep_name", ""),
                ("b", "e2", "rep", "csm_name", ""),
                ("a", "e1", "csm", "csm_name", ""),
                ("a", "e1", "channel", None, ""),
            ]

    monkeypatch.setattr(harness, "get_registry", _Registry)
    assert harness._self_attributes() == {"csm": "csm_name"}


def test_label_mode_without_mode_names_the_golden() -> None:
    golden = {"id": "g-1", "label_modes": {"person_name": {"bucket_size": 3}}}
    with pytest.raises(ValueError, match="g-1"):
        harness._policy(_user(), golden)


@pytest.mark.parametrize("bucket_size", ["five", 2.5, True, None])
def test_non_integer_bucket_size_names_the_golden(bucket_size: object) -> None:
    golden = {
        "id": "g-2",
        "label_modes": {"person_name": {"mode": "bucket", "bucket_size": bucket_size}},
    }
    with pytest.raises(ValueError, match=r"golden 'g-2': label_modes\.person_name"):
        harness._label_modes(golden)


@pytest.mark.parametrize("attributes", [["rep_name"], "rep_name", 3])
def test_non_mapping_attributes_names_the_golden(attributes: object) -> None:
    golden = {"id": "g-3", "attributes": attributes}
    with pytest.raises(ValueError, match=r"golden 'g-3': attributes must be a mapping"):
        harness._attributes(_user(), golden)
