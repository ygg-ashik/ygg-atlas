"""Access: what a caller may do and see (spec §5).

Other modules import only from here.
"""

from app.access.catalog import (
    ADMIN_AUDIT,
    ADMIN_GROUPS,
    ADMIN_USERS,
    CHAT_USE,
    MCP_USE,
)
from app.access.dependencies import access_error_handler, get_policy, require_capability
from app.access.errors import AccessError, PolicyUnavailableError
from app.access.evaluator import evaluate
from app.access.facts import GrantFacts, PolicyInputs, UserFacts
from app.access.policy import Policy
from app.access.router import router as access_router
from app.access.service import policy_for
from app.access.startup import prepare_access

__all__ = [
    "ADMIN_AUDIT",
    "ADMIN_GROUPS",
    "ADMIN_USERS",
    "CHAT_USE",
    "MCP_USE",
    "AccessError",
    "GrantFacts",
    "Policy",
    "PolicyInputs",
    "PolicyUnavailableError",
    "UserFacts",
    "access_error_handler",
    "access_router",
    "evaluate",
    "get_policy",
    "policy_for",
    "prepare_access",
    "require_capability",
]
