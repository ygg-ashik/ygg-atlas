"""Who changes access, and the checks every admin write makes on them."""

from dataclasses import dataclass
from typing import Self
from uuid import UUID

from app.access.errors import AccessDeniedError
from app.access.facts import DEFAULT_TENANT
from app.access.policy import Policy


@dataclass(frozen=True, slots=True)
class Actor:
    """Who changes access. `policy` is None only for the trusted CLI."""

    user_id: UUID | None
    via: str  # 'api' | 'cli'
    tenant: str
    policy: Policy | None

    @classmethod
    def from_policy(cls, policy: Policy) -> Self:
        return cls(policy.user_id, "api", policy.tenant, policy)

    @classmethod
    def cli(cls, tenant: str = DEFAULT_TENANT) -> Self:
        """The trusted CLI operator: skips capability and no-widening checks.
        Never construct this from request or agent code."""
        return cls(None, "cli", tenant, None)

    def require(self, capability: str) -> None:
        if self.policy is not None and not self.policy.has(capability):
            msg = f"This needs {capability}. Ask an atlas admin."
            raise AccessDeniedError(msg)

    def require_any(self, *capabilities: str) -> None:
        if self.policy is not None and not any(
            self.policy.has(c) for c in capabilities
        ):
            msg = f"This needs {' or '.join(capabilities)}. Ask an atlas admin."
            raise AccessDeniedError(msg)

    def require_member_admin(self, group_id: UUID) -> None:
        if self.policy is not None and not self.policy.can_manage_members(group_id):
            msg = "Only atlas admins and the group's managers can change its members."
            raise AccessDeniedError(msg)


def require_clearance(actor: Actor, clearance: str) -> None:
    """Granting a clearance, or lifting a clearance
    deny, widens access, so an API actor must hold that clearance; the
    trusted CLI (policy None) is exempt."""
    if actor.policy is not None and not actor.policy.has_clearance(clearance):
        msg = (
            f"You can only grant or lift the '{clearance}' clearance if you "
            "hold it yourself."
        )
        raise AccessDeniedError(msg)
