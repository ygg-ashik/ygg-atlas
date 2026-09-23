"""LLM provider loops.

Each provider module exposes:

    run_tool_loop(client, model, system, messages, execute_tool, max_rounds)

an async generator yielding SSE-ready events:
  {type: 'token', content}    streamed text delta
  {type: 'tool_status', tool} a tool is being executed
and exactly one terminal event:
  {type: 'final', content, token_usage}   normal completion
  {type: 'error', message}                tool budget exhausted

`execute_tool(name, args) -> dict` is supplied by the caller (which also
harvests provenance). `messages` is plain [{'role', 'content'}] history + the
new user message; providers own their native tool-exchange message formats.
"""

from app.agent.providers import anthropic_loop, openai_loop

__all__ = ["anthropic_loop", "openai_loop"]
