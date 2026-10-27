"""Typed, JSON-serialisable graph state. No secrets, no raw documents (ids and small facts only)."""

from typing import Any, TypedDict


class QualificationState(TypedDict, total=False):
    workflow_id: str
    lead_id: str
    resume: bool  # True => entering after a human decision
    steps: int  # loop/budget guard
    errors: list[str]
    status: str  # running | awaiting_approval | completed | rejected | revision_requested | failed
    icp_id: str
    icp_version: int
    validation_errors: list[str]
    duplicate_ids: list[str]
    injection_hits: list[str]
    research_status: str  # disabled | ok | unavailable
    snippets: list[dict[str, Any]]
    score_total: float
    score_priority: str
    disqualified: bool
    ai_status: str  # not_run | ok | unavailable | malformed | not_configured
    evaluation_id: str
    approval_id: str
    approval_status: str
    draft_id: str
    final_lead_status: str
