from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import Container, CurrentUser, SalesUser, get_container, get_db
from app.models import Lead, User
from app.models.enums import DraftStatus
from app.schemas.qualification import DraftOut, DraftRequest, DraftUpdate
from app.services import lead_service, outreach_service

router = APIRouter(tags=["outreach"])


def _out(db: Session, d) -> DraftOut:
    out = DraftOut.model_validate(d)
    lead = db.get(Lead, d.lead_id)
    if lead:
        out.lead_name, out.company_name = lead.full_name, lead.company_name
    return out


@router.post("/leads/{lead_id}/drafts", response_model=DraftOut, status_code=201)
def create_draft(lead_id: str, body: DraftRequest, user: User = SalesUser, db: Session = Depends(get_db), c: Container = Depends(get_container)):
    lead = lead_service.get_lead(db, lead_id)
    d = outreach_service.generate_draft(
        db, lead=lead, draft_type=body.draft_type, cta=body.call_to_action, actor_id=user.id, llm=c.llm, settings=c.settings
    )
    db.commit()
    return _out(db, d)


@router.get("/drafts", response_model=list[DraftOut])
def list_drafts(
    status: DraftStatus | None = None, lead_id: str | None = Query(None, max_length=32), _: User = CurrentUser, db: Session = Depends(get_db)
):
    return [_out(db, d) for d in outreach_service.list_drafts(db, status=status, lead_id=lead_id)]


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
def update_draft(draft_id: str, body: DraftUpdate, user: User = SalesUser, db: Session = Depends(get_db)):
    d = outreach_service.update_draft(
        db,
        draft_id,
        subject=body.subject,
        body=body.body,
        follow_up=body.follow_up_date,
        actor_id=user.id,
        set_follow_up="follow_up_date" in body.model_fields_set,
    )
    return _out(db, d)


@router.post("/drafts/{draft_id}/mark-sent", response_model=DraftOut)
def mark_sent(draft_id: str, body: DraftUpdate | None = None, user: User = SalesUser, db: Session = Depends(get_db)):
    fu = body.follow_up_date if body else None
    return _out(db, outreach_service.mark_sent_manually(db, draft_id, actor_id=user.id, follow_up=fu))
