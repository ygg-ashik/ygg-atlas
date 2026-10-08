"""Token verification contract. Implemented by identity.firebase; faked in tests."""

from dataclasses import dataclass
from typing import Protocol


class InvalidTokenError(Exception):
    """The bearer token is malformed, expired, revoked or not for this project."""


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    uid: str
    email: str
    email_verified: bool
    name: str
    auth_time: int  # epoch seconds of the original sign-in


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> VerifiedToken: ...

    async def revoke(self, firebase_uid: str) -> None: ...
