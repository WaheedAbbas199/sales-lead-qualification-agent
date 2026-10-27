from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    REVIEWER = "reviewer"
    SALES = "sales"


class LeadStatus(StrEnum):
    NEW = "new"
    QUALIFYING = "qualifying"
    PENDING_REVIEW = "pending_review"
    QUALIFIED = "qualified"
    NURTURE = "nurture"
    DISQUALIFIED = "disqualified"
    NEEDS_REVISION = "needs_revision"
    ARCHIVED = "archived"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Timeline(StrEnum):
    IMMEDIATE = "immediate"
    WITHIN_3_MONTHS = "within_3_months"
    WITHIN_6_MONTHS = "within_6_months"
    EXPLORING = "exploring"
    UNKNOWN = "unknown"


class Consent(StrEnum):
    UNKNOWN = "unknown"
    GRANTED = "granted"
    OPTED_OUT = "opted_out"


class CriterionStatus(StrEnum):
    MATCHED = "matched"
    PARTIAL = "partial"
    NOT_MATCHED = "not_matched"
    UNKNOWN = "unknown"


class BantDimension(StrEnum):
    BUDGET = "budget"
    AUTHORITY = "authority"
    NEED = "need"
    TIMELINE = "timeline"


class BantStatus(StrEnum):
    CONFIRMED = "confirmed"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    UNKNOWN = "unknown"
    NOT_MATCHED = "not_matched"


class Provenance(StrEnum):
    """Where a fact came from. The UI always shows this next to a claim."""

    USER_PROVIDED = "user_provided"
    VERIFIED_SOURCE = "verified_source"  # direct observation from an authorised source with URL
    SEARCH_SNIPPET = "search_snippet"  # search result snippet: a lead, NOT proof
    AI_INFERRED = "ai_inferred"
    UNKNOWN = "unknown"


class WorkflowStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"
    FAILED = "failed"


ACTIVE_WORKFLOW_STATUSES = (WorkflowStatus.QUEUED, WorkflowStatus.RUNNING, WorkflowStatus.AWAITING_APPROVAL)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


class DraftType(StrEnum):
    INTRODUCTION = "introduction"
    DISCOVERY_MEETING = "discovery_meeting"
    FOLLOW_UP = "follow_up"
    MISSING_INFO = "missing_info_request"


class DraftStatus(StrEnum):
    DRAFT = "draft"
    SENT_MANUALLY = "sent_manually"
    DISCARDED = "discarded"
