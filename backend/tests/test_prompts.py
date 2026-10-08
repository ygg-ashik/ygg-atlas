"""System prompt: the clarify-over-guess rule references the real control tool."""

from app.agent.blocks import CLARIFY_TOOL
from app.agent.prompts import build_system_prompt


def test_prompt_tells_the_model_to_clarify_instead_of_guessing():
    prompt = build_system_prompt()
    assert CLARIFY_TOOL["name"] in prompt
    assert "instead of guessing" in prompt
    assert "at most once per turn" in prompt
