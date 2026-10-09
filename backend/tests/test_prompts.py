"""System prompt: the clarify-over-guess rule references the real control tool."""

from app.agent.blocks import CLARIFY_TOOL
from app.agent.prompts import build_system_prompt


def test_prompt_tells_the_model_to_clarify_instead_of_guessing():
    prompt = build_system_prompt()
    assert CLARIFY_TOOL["name"] in prompt
    assert "instead of guessing" in prompt
    assert "at most once per turn" in prompt


def test_prompt_forbids_plain_text_clarifying_questions() -> None:
    prompt = build_system_prompt()
    assert "never ask a clarifying question in plain text" in prompt


def test_prompt_routes_breakdown_requests_to_the_breakdown_tool() -> None:
    prompt = build_system_prompt()
    assert "metric_breakdown" in prompt
    assert "break down" in prompt


def test_prompt_treats_vague_unbounded_questions_as_ambiguous() -> None:
    assert "vague business word" in build_system_prompt()


def test_prompt_explains_missing_access_honestly() -> None:
    prompt = build_system_prompt()
    assert "isn't available" in prompt
    assert "atlas admin" in prompt
    assert "doesn't exist" in prompt
    assert "another way" in prompt


def test_prompt_frames_a_miss_as_scoped_to_the_users_access() -> None:
    """Rule 2 + rule 10 must agree: partial access never reads as "this data
    doesn't exist" — only as "not among what you can see"."""
    prompt = build_system_prompt()
    assert "the data available to the user" in prompt
    assert "may be outside the user's access" in prompt
    # The phrasing the model should say back to the user stays second person.
    assert '"among the data available to you' in prompt
    assert '"this may be outside your access"' in prompt


def test_prompt_access_rules_refer_to_the_person_as_the_user() -> None:
    """The prompt addresses the model; outside quoted phrasing, the person is
    "the user", never "you"/"your access"."""
    prompt = build_system_prompt()
    assert "can check your access" not in prompt
    assert "If you expected" not in prompt
    assert "it may be outside your access" not in prompt
