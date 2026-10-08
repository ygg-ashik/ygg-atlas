"""Response shapes for identity routes (separate from the users table)."""

from uuid import UUID

from pydantic import BaseModel

from app.identity.principal import Principal


class MeOut(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    role: str
    kind: str
    tenant: str
    auth_method: str

    @classmethod
    def from_principal(cls, principal: Principal) -> "MeOut":
        return cls(
            user_id=principal.user_id,
            email=principal.email,
            display_name=principal.display_name,
            role=principal.role,
            kind=principal.kind,
            tenant=principal.tenant,
            auth_method=principal.auth_method,
        )
