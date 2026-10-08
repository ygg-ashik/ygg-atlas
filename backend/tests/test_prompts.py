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
