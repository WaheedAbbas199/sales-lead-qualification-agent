"""Lead lifecycle: create / update / archive / merge / CSV import. All writes are audited."""

import csv
import io
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from app.models import Lead
from app.models.enums import LeadStatus
from app.repositories import lead_repository as repo
from app.repositories import qualification_repository as qrepo
from app.schemas.lead import DuplicateCandidate, ImportResult, ImportRowError, LeadCreate, LeadUpdate
from app.services import normalization as n
from app.services.audit_service import activity, audit
from app.services.safety import detect_injection

CSV_COLUMNS = [
    "first_name",
    "last_name",
    "company_name",
    "email",
    "website",
    "industry",
    "country",
    "region",
    "company_size",
    "job_title",
    "is_decision_maker",
    "requirements",
    "budget_usd",
    "timeline",
    "consent",
    "source",
]
REQUIRED_COLUMNS = ["first_name", "company_name"]
SAMPLE_ROW = [
    "Jordan",
    "Reyes",
    "Reyes Heating & Cooling",
    "jordan@example.com",
    "reyes-hvac.example.com",
    "HVAC",
    "US",
    "Texas",
    "18",
    "Owner",
    "yes",
    "We miss calls after hours and want automatic follow-up",
    "4000",
    "within 3 months",
    "unknown",
    "CSV sample",
]


def _apply_normalised(lead: Lead, data: dict) -> None:
    """Copy validated schema data onto the ORM row and keep derived/normalised columns in sync."""
    for key, value in data.items():
        if key in ("source", "email", "website", "industry", "country"):
            continue
        setattr(lead, key, value)
    if "email" in data:
        lead.email = data["email"]
        lead.email_normalized = data["email"]  # already normalised by the schema validator
    if "website" in data:
        lead.website = data["website"]
        lead.website_domain = n.normalize_url(data["website"])[1] if data["website"] else None
    if "industry" in data:
        lead.industry = data["industry"]
        lead.industry_normalized = n.normalize_industry(data["industry"])
    if "country" in data:
        lead.country = n.normalize_country(data["country"])
    lead.suspicious_content = bool(detect_injection(lead.requirements, lead.job_title, lead.company_name))


def _dup_candidates(session: Session, lead: Lead) -> list[DuplicateCandidate]:
    return [
        DuplicateCandidate(lead_id=d.id, full_name=d.full_name, company_name=d.company_name, email=d.email, reason=why)
        for d, why in repo.find_possible_duplicates(
            session,
            first_name=lead.first_name,
            last_name=lead.last_name,
            company_name=lead.company_name,
            website_domain=lead.website_domain,
            exclude_id=lead.id,
        )
    ]


def create_lead(
    session: Session, payload: LeadCreate, *, actor_id: str | None, source_kind: str = "manual", commit: bool = True
) -> tuple[Lead, list[DuplicateCandidate]]:
    data = payload.model_dump()
    source_name = data.pop("source", None)
    if data.get("email"):
        existing = repo.get_by_email(session, data["email"])
        if existing:
            raise ConflictError("A lead with this email already exists", details={"existing_lead_id": existing.id})
    lead = Lead(created_by=actor_id)
    _apply_normalised(lead, data)
    if source_name:
        lead.source_id = repo.get_or_create_source(session, source_name, source_kind).id
    session.add(lead)
    try:
        session.flush()
    except IntegrityError as exc:  # concurrent insert of the same email lost the race
        if commit:  # inside an import savepoint the caller's `begin_nested` handles the rollback
            session.rollback()
        raise ConflictError("A lead with this email already exists") from exc
    dups = _dup_candidates(session, lead)
    audit(
        session,
        actor_id=actor_id,
        action="lead.create",
        entity_type="lead",
        entity_id=lead.id,
        details={"source": source_name, "possible_duplicates": len(dups), "suspicious": lead.suspicious_content},
    )
    activity(session, lead_id=lead.id, actor_id=actor_id, kind="created", message="Lead created")
    if lead.suspicious_content:
        audit(
            session,
            actor_id=actor_id,
            action="security.suspicious_content",
            entity_type="lead",
            entity_id=lead.id,
            details={"fields": "requirements/job_title/company_name"},
        )
    if commit:
        session.commit()
    return lead, dups


def get_lead(session: Session, lead_id: str) -> Lead:
    lead = repo.get(session, lead_id)
    if not lead:
        raise NotFoundError("Lead not found")
    return lead


def update_lead(session: Session, lead_id: str, payload: LeadUpdate, *, actor_id: str) -> Lead:
    lead = get_lead(session, lead_id)
    changes = payload.model_dump(exclude_unset=True)
    source_name = changes.pop("source", None) if "source" in changes else None
    if "email" in changes and changes["email"]:
        other = repo.get_by_email(session, changes["email"])
        if other and other.id != lead.id:
            raise ConflictError("Another lead already uses this email", details={"existing_lead_id": other.id})
    for required in ("first_name", "company_name"):
        if required in changes and not changes[required]:
            raise ValidationFailed(f"{required} must not be blank")
    before = {k: str(getattr(lead, k, None)) for k in changes}
    _apply_normalised(lead, changes)
    if source_name:
        lead.source_id = repo.get_or_create_source(session, source_name).id
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Another lead already uses this email") from exc
    audit(
        session, actor_id=actor_id, action="lead.update", entity_type="lead", entity_id=lead.id, details={"fields": sorted(changes), "before": before}
    )
    activity(session, lead_id=lead.id, actor_id=actor_id, kind="updated", message=f"Updated: {', '.join(sorted(changes))}")
    session.commit()
    return lead


def archive_lead(session: Session, lead_id: str, *, actor_id: str) -> Lead:
    from app.db.base import utcnow

    lead = get_lead(session, lead_id)
    if qrepo.active_workflow(session, lead.id):
        raise ConflictError("Lead has an active qualification workflow; finish or reject it first")
    lead.status = LeadStatus.ARCHIVED
    lead.archived_at = utcnow()
    audit(session, actor_id=actor_id, action="lead.archive", entity_type="lead", entity_id=lead.id)
    activity(session, lead_id=lead.id, actor_id=actor_id, kind="archived", message="Lead archived")
    session.commit()
    return lead


def restore_lead(session: Session, lead_id: str, *, actor_id: str) -> Lead:
    lead = get_lead(session, lead_id)
    if lead.status != LeadStatus.ARCHIVED:
        raise ConflictError("Lead is not archived")
    lead.status = LeadStatus.NEW
    lead.archived_at = None
    audit(session, actor_id=actor_id, action="lead.restore", entity_type="lead", entity_id=lead.id)
    activity(session, lead_id=lead.id, actor_id=actor_id, kind="restored", message="Lead restored")
    session.commit()
    return lead


MERGE_FIELDS = [
    "last_name",
    "email",
    "website",
    "industry",
    "country",
    "region",
    "company_size",
    "job_title",
    "is_decision_maker",
    "requirements",
    "budget_usd",
    "source_id",
]


def merge_leads(session: Session, primary_id: str, duplicate_id: str, *, actor_id: str) -> Lead:
    """Fill EMPTY fields of the primary from the duplicate. Conflicting values are never overwritten; they are
    recorded in the audit trail for the human to resolve. The duplicate is archived (not deleted)."""
    from app.db.base import utcnow

    if primary_id == duplicate_id:
        raise ValidationFailed("Cannot merge a lead into itself")
    primary, dup = get_lead(session, primary_id), get_lead(session, duplicate_id)
    if qrepo.active_workflow(session, primary.id) or qrepo.active_workflow(session, dup.id):
        raise ConflictError("Finish active workflows before merging")
    filled, conflicts = [], {}
    dup_email, dup_email_norm = dup.email, dup.email_normalized
    for f in MERGE_FIELDS:
        pv, dv = getattr(primary, f), getattr(dup, f)
        if dv in (None, ""):
            continue
        if pv in (None, ""):
            if f == "email":
                dup.email_normalized = None  # release the unique value first
                session.flush()
                primary.email, primary.email_normalized = dup_email, dup_email_norm
            else:
                setattr(primary, f, dv)
                if f == "website":
                    primary.website_domain = dup.website_domain
                if f == "industry":
                    primary.industry_normalized = dup.industry_normalized
            filled.append(f)
        elif str(pv) != str(dv):
            conflicts[f] = {"kept": str(pv), "discarded": str(dv)}
    dup.status = LeadStatus.ARCHIVED
    dup.archived_at = utcnow()
    audit(
        session,
        actor_id=actor_id,
        action="lead.merge",
        entity_type="lead",
        entity_id=primary.id,
        details={"merged_from": dup.id, "filled": filled, "conflicts": conflicts},
    )
    activity(
        session,
        lead_id=primary.id,
        actor_id=actor_id,
        kind="merged",
        message=f"Merged duplicate {dup.full_name} (filled: {', '.join(filled) or 'nothing'}; conflicts kept: {len(conflicts)})",
    )
    activity(session, lead_id=dup.id, actor_id=actor_id, kind="merged_into", message=f"Merged into lead {primary.id}")
    session.commit()
    return primary


# ----------------------------- CSV import -----------------------------


def csv_template() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    w.writerow(SAMPLE_ROW)
    return buf.getvalue()


def _csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection in CSV we hand back to the user."""
    return "'" + value if value and value[0] in "=+-@\t\r" else value


def _row_to_payload(row: dict[str, str]) -> LeadCreate:
    raw = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k in CSV_COLUMNS}
    data: dict = {k: (v or None) for k, v in raw.items()}
    data["first_name"] = raw.get("first_name") or ""
    data["last_name"] = raw.get("last_name") or ""
    data["company_name"] = raw.get("company_name") or ""
    if data.get("company_size"):
        try:
            data["company_size"] = int(float(str(data["company_size"]).replace(",", "")))
        except ValueError as exc:
            raise ValueError("company_size must be a whole number") from exc
    data["is_decision_maker"] = n.parse_optional_bool(data.get("is_decision_maker"))
    budget = n.parse_budget(data.get("budget_usd"))
    data["budget_usd"] = Decimal(str(budget)) if budget is not None else None
    tl = (data.get("timeline") or "unknown").lower().replace("-", "_").replace(" ", "_")
    data["timeline"] = tl
    data["consent"] = (data.get("consent") or "unknown").lower().replace(" ", "_")
    return LeadCreate(**{k: v for k, v in data.items() if v is not None or k in ("last_name",)})


def import_csv(session: Session, *, content: bytes, filename: str, settings: Settings, actor_id: str) -> ImportResult:
    if not filename.lower().endswith(".csv"):
        raise ValidationFailed("Only .csv files are accepted")
    if len(content) > settings.csv_max_bytes:
        raise ValidationFailed(f"File too large (max {settings.csv_max_bytes} bytes)")
    if b"\x00" in content:
        raise ValidationFailed("File does not look like a text CSV")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("File must be UTF-8 encoded") from exc
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise ValidationFailed(f"Missing required column(s): {', '.join(missing)}", details={"expected": CSV_COLUMNS})
    reader.fieldnames = headers
    ignored = [h for h in headers if h not in CSV_COLUMNS]

    created = skipped = rejected = possible = total = 0
    errors: list[ImportRowError] = []
    rejected_rows: list[dict] = []
    seen_emails: set[str] = set()
    for idx, row in enumerate(reader, start=2):  # row 1 is the header
        total += 1
        if total > settings.csv_max_rows:
            raise ValidationFailed(f"Too many rows (max {settings.csv_max_rows})")
        try:
            payload = _row_to_payload(row)
        except (ValidationError, ValueError) as exc:
            msgs = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
            errors.append(ImportRowError(row=idx, errors=msgs))
            rejected += 1
            rejected_rows.append({**{c: _csv_safe(str(row.get(c) or "")) for c in CSV_COLUMNS}, "row": idx, "errors": "; ".join(msgs)})
            continue
        if payload.email and payload.email in seen_emails:
            skipped += 1
            continue
        try:
            with session.begin_nested():  # savepoint: one bad row never poisons the whole import
                lead, dups = create_lead(session, payload, actor_id=actor_id, source_kind="csv", commit=False)
            if payload.email:
                seen_emails.add(payload.email)
            created += 1
            possible += 1 if dups else 0
        except ConflictError:
            skipped += 1
    audit(
        session,
        actor_id=actor_id,
        action="lead.import_csv",
        entity_type="lead",
        details={"file": filename[:100], "rows": total, "created": created, "skipped": skipped, "rejected": rejected},
    )
    session.commit()
    report = None
    if rejected_rows:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["row", "errors", *CSV_COLUMNS])
        w.writeheader()
        w.writerows(rejected_rows)
        report = buf.getvalue()
    return ImportResult(
        total_rows=total,
        created=created,
        skipped_duplicates=skipped,
        rejected=rejected,
        possible_duplicates=possible,
        errors=errors[:200],
        ignored_columns=ignored,
        error_report_csv=report,
    )
