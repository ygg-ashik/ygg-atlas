"""The authenticated caller of one request. Built only by the identity service."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

AuthMethod = Literal["web", "oauth", "pat", "service", "dev"]


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    email: str
    display_name: str
    role: str
    kind: str
    tenant: str
    auth_method: AuthMethod
    # The MCP credential behind this request (phase 4); None on the web door.
    token_id: UUID | None = None
    client_id: str | None = None
