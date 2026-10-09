"""Identity failures, mapped to HTTP status codes by identity.dependencies."""


class UnauthenticatedError(Exception):
    """401: the caller is not (or no longer) signed in."""


class ForbiddenError(Exception):
    """403: the caller is known but may not use atlas."""


class IdentityUnavailableError(Exception):
    """503: the identity provider is unreachable; the caller's session is fine."""


class CredentialRuleError(Exception):
    """400: a credential request breaks a rule (name, lifetime, wrong user kind)."""


class CredentialLimitError(Exception):
    """409: the user already holds the maximum number of live personal tokens."""


class CredentialNotFoundError(Exception):
    """404: no such token, family or service account, or it is not the caller's."""
