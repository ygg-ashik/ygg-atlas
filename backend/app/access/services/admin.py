"""Access administration: one service per topic over one shared writer."""

from app.access.repositories import AccessRepository
from app.access.service import AccessService
from app.access.services.audit import AuditService
from app.access.services.grants import GrantService
from app.access.services.groups import GroupService
from app.access.services.members import MemberService
from app.access.services.requests import RequestService
from app.access.services.row_field import RowFieldService
from app.access.services.users import UserService
from app.access.services.writer import AccessWriter
from app.identity import TokenVerifier


class AccessAdmin:
    """The topic services for one session, wired to one `AccessWriter`, so
    every write takes the same lock and lands with one version bump.

    Callers pick the topic: `admin.groups.create_group(actor, payload)`.
    """

    def __init__(
        self,
        repo: AccessRepository,
        access: AccessService,
        verifier: TokenVerifier | None = None,
    ) -> None:
        self.writer = AccessWriter(repo)
        self.groups = GroupService(repo, self.writer)
        self.members = MemberService(repo, self.writer)
        self.row_field = RowFieldService(repo, self.writer)
        self.grants = GrantService(repo, self.writer, self.row_field)
        self.users = UserService(repo, self.writer, access, verifier)
        self.audit = AuditService(repo)
        self.requests = RequestService(
            repo, access, self.writer, self.members, self.users, self.grants
        )
