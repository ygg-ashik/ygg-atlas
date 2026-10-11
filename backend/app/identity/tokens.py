"""Token verification contract. Implemented by identity.firebase; faked in tests."""

from dataclasses import dataclass
from typing import Protocol


class InvalidTokenError(Exception):
    """The bearer token is malformed, expired, revoked or not for this project."""


class ExpiredTokenError(InvalidTokenError):
    """A real, unrevoked bearer whose only fault is its expiry. Same generic message
    for the caller; edges may tell it apart (a client to re-authenticate, not a
    guess: ruling E1)."""


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    uid: str
    email: str
    email_verified: bool
    name: str
    auth_time: int  # epoch seconds of the original sign-in
    sign_in_provider: str  # e.g. "google.com", "password", "emailLink"


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> VerifiedToken: ...

    async def revoke(self, firebase_uid: str) -> None: ...
