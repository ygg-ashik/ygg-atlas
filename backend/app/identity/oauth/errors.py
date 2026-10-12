"""What the OAuth service refuses with. Every description here is safe to show:
the real reason goes to a log field, never to the client."""

from typing import Final, Literal

INVALID_REQUEST: Final = "invalid_request"
INVALID_GRANT: Final = "invalid_grant"
RegistrationErrorCode = Literal["invalid_redirect_uri", "invalid_client_metadata"]

DEAD_CODE: Final = "The authorization code is no longer valid."
DEAD_REFRESH: Final = "The refresh token is no longer valid."
INELIGIBLE: Final = "Authorization is no longer valid. Sign in again."
_UNAVAILABLE: Final = "The grant could not be processed. Try again."


class OAuthRegistrationError(Exception):
    """Dynamic registration refused (RFC 7591 error codes)."""

    def __init__(self, error: RegistrationErrorCode, description: str) -> None:
        super().__init__(description)
        self.error: RegistrationErrorCode = error
        self.description = description


class OAuthRequestError(Exception):
    """An /authorize request refused; `description` is safe to show."""

    error: Final = INVALID_REQUEST

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


class OAuthGrantError(Exception):
    """A code or refresh grant refused; `description` is safe to show."""

    error: Final = INVALID_GRANT

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


class AuthorizationRequestNotFoundError(Exception):
    """Unknown, expired or already consumed authorization request (404)."""


class EligibilityUnavailableError(Exception):
    """An `Eligibility` check could not be made (not "not eligible"). The grant is
    refused with nothing issued, and nothing is revoked or spent."""


class GrantUnavailableError(Exception):
    """A grant could not be processed for a transient reason: a database error or
    an eligibility check that could not be made. Nothing was issued (fail closed),
    and nothing the client holds was spent or revoked, so it should retry. Not an
    OAuthGrantError on purpose: the edge answers `server_error`, because
    `invalid_grant` would make a client drop a code or refresh token that is still
    good. The message is fixed and generic."""

    def __init__(self) -> None:
        super().__init__(_UNAVAILABLE)
