"""Allow-listed tools with explicit tiers. The LLM never calls these: only graph nodes do.

Tiers: READ (no side effects) < DRAFT (internal, reversible) < WRITE (internal records) < EXTERNAL (irreversible).
Anything above READ that is outward-facing must pass `require_approved`, which re-reads the DB (fail closed).
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

from sqlalchemy.orm import Session

from app.core.exceptions import PermissionDenied
from app.models import Approval
from app.models.enums import ApprovalStatus


class Tier(IntEnum):
    READ = 0
    DRAFT = 1
    WRITE = 2
    EXTERNAL = 3


@dataclass(frozen=True)
class Tool:
    name: str
    tier: Tier
    fn: Callable
    requires_approval: bool


class ToolRegistry:
    def __init__(self, session: Session):
        self._session = session
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, tier: Tier, fn: Callable, *, requires_approval: bool | None = None) -> None:
        needs = (tier >= Tier.DRAFT) if requires_approval is None else requires_approval
        self._tools[name] = Tool(name, tier, fn, needs)

    def require_approved(self, workflow_id: str) -> Approval:
        approval = self._session.query(Approval).filter(Approval.workflow_id == workflow_id).one_or_none()
        if approval is None or approval.status != ApprovalStatus.APPROVED or approval.reviewer_id is None:
            raise PermissionDenied("Human approval required before this action")
        return approval

    def call(self, name: str, *, workflow_id: str, **kwargs):
        tool = self._tools.get(name)
        if tool is None:
            raise PermissionDenied(f"Tool '{name}' is not allow-listed")
        if tool.requires_approval:
            self.require_approved(workflow_id)  # DB re-check, never trust graph state
        return tool.fn(**kwargs)
