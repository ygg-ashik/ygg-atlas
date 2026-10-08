"""Access failures. Each carries the HTTP status the API maps it to."""

from typing import ClassVar


class AccessError(Exception):
    status_code: ClassVar[int] = 400


class AccessDeniedError(AccessError):
    """403: the caller may not do this."""

    status_code: ClassVar[int] = 403


class NotFoundError(AccessError):
    status_code: ClassVar[int] = 404


class ConflictError(AccessError):
    status_code: ClassVar[int] = 409


class InvalidChangeError(AccessError):
    status_code: ClassVar[int] = 422


class PolicyUnavailableError(AccessError):
    """503: the policy could not be evaluated, so everything is denied (spec §12)."""

    status_code: ClassVar[int] = 503
