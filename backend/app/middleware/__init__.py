"""DEPRECATED compatibility shim over `app.identity` (use `get_principal` instead).

Kept so `app.insights` (Hybrid Glass Track E) keeps working without edits from this
branch. Removal is tracked in ARCHITECTURE.md §6.
"""

from dataclasses import dataclass

from fastapi import Depends

from app.identity import Principal, get_principal


@dataclass(frozen=True)
class AuthUser:
    uid: str  # the atlas user id as text
    email: str


async def get_current_user(principal: Principal = Depends(get_principal)) -> AuthUser:
    return AuthUser(uid=str(principal.user_id), email=principal.email)


__all__ = ["AuthUser", "get_current_user"]
