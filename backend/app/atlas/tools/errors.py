"""The atlas tools' errors and the chat-only denial payload."""

from typing import Any

POLICY_FAILED = "the access check failed"
# Result key of a policy denial's {"resource", "label"} (chat-only, never sent
# to a model or an MCP client).
DENIED_KEY = "denied"


class AtlasToolError(Exception):
    """User-visible tool failure.

    The agent should relay/explain it, not retry blindly.
    """


class AtlasAccessDeniedError(AtlasToolError):
    """The caller's policy denies a governed resource.

    `resource` is set only when the policy itself said no, so the denial can
    offer an access request; a scope or policy-evaluation failure leaves it None.
    """

    def __init__(
        self,
        label: str,
        reason: str,
        message: str | None = None,
        *,
        resource: str | None = None,
    ) -> None:
        super().__init__(
            message
            or f"{label} isn't available to you. Ask an atlas admin if you need it."
        )
        self.label = label
        self.reason = reason
        self.resource = resource


class AtlasPolicyError(AtlasToolError):
    """The caller's policy could not be evaluated; fail closed."""


def without_denial(result: dict[str, Any]) -> dict[str, Any]:
    """`result` minus the chat-only denial payload: what models and MCP see."""
    return {k: v for k, v in result.items() if k != DENIED_KEY}


def policy_failed(label: str) -> AtlasAccessDeniedError:
    """An honest denial for a policy that could not be evaluated."""
    return AtlasAccessDeniedError(
        label,
        POLICY_FAILED,
        message=(
            f"{label} couldn't be checked against your access right now. "
            "Try again shortly."
        ),
    )
