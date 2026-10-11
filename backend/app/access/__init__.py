"""Access: what a caller may do and see (spec §5).

Other modules import only from here.
"""

from app.access.admin import AccessAdmin, Actor
from app.access.catalog import (
    ADMIN_AUDIT,
    ADMIN_CLIENTS,
    ADMIN_GROUPS,
    ADMIN_TOKENS,
    ADMIN_USERS,
    CHAT_USE,
    MCP_USE,
    TOKENS_CREATE,
)
from app.access.dependencies import (
    access_error_handler,
    get_access_admin,
    get_actor,
    get_policy,
    require_capability,
)
from app.access.errors import AccessError, PolicyUnavailableError
from app.access.evaluator import evaluate
from app.access.facts import GrantFacts, PolicyInputs, UserFacts
from app.access.policy import Policy
from app.access.router import router as access_router
from app.access.service import policy_for
from app.access.startup import prepare_access, sync_scope_dimensions

__all__ = [
    "ADMIN_AUDIT",
    "ADMIN_CLIENTS",
    "ADMIN_GROUPS",
    "ADMIN_TOKENS",
    "ADMIN_USERS",
    "CHAT_USE",
    "MCP_USE",
    "TOKENS_CREATE",
    "AccessAdmin",
    "AccessError",
    "Actor",
    "GrantFacts",
    "Policy",
    "PolicyInputs",
    "PolicyUnavailableError",
    "UserFacts",
    "access_error_handler",
    "access_router",
    "evaluate",
    "get_access_admin",
    "get_actor",
    "get_policy",
    "policy_for",
    "prepare_access",
    "require_capability",
    "sync_scope_dimensions",
]
