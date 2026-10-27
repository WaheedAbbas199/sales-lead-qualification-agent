"""Deterministic BANT assessment from the lead's own (user-provided) data.

Every conclusion carries evidence text + provenance. Unknown stays unknown - nothing is invented.
The LLM may add *separate* `ai`-origin suggestions, which never replace these rule-based results.
"""

from dataclasses import dataclass

from app.models.enums import BantDimension, BantStatus, Provenance, Timeline
from app.services.icp_config import ICPConfig
from app.services.scoring_service import LeadFacts, matched_services


@dataclass
class BantItem:
    dimension: BantDimension
    status: BantStatus
    evidence_text: str | None
    provenance: Provenance
    rationale: str
    clarification_needed: str | None = None
    origin: str = "rules"


def assess_bant(f: LeadFacts, icp: ICPConfig) -> list[BantItem]:
    items: list[BantItem] = []

    # Budget
    if f.budget_usd is None:
        items.append(
            BantItem(
                BantDimension.BUDGET, BantStatus.UNKNOWN, None, Provenance.UNKNOWN, "No budget was provided.", "Ask for an approximate budget range."
            )
        )
    else:
        offer_mins = [s.min_budget_usd for s in icp.services if s.min_budget_usd]
        floor = icp.min_budget_usd if icp.min_budget_usd is not None else (min(offer_mins) if offer_mins else None)
        if floor is None:
            st, why = BantStatus.PARTIALLY_CONFIRMED, "Budget stated but no minimum is configured to compare against."
        elif f.budget_usd >= floor:
            st, why = BantStatus.CONFIRMED, f"Stated budget ${f.budget_usd:,.0f} meets the configured minimum ${floor:,.0f}."
        elif f.budget_usd >= floor * 0.5:
            st, why = BantStatus.PARTIALLY_CONFIRMED, f"Stated budget ${f.budget_usd:,.0f} is below ${floor:,.0f}; scope may need adjusting."
        else:
            st, why = BantStatus.NOT_MATCHED, f"Stated budget ${f.budget_usd:,.0f} is far below ${floor:,.0f}."
        items.append(
            BantItem(
                BantDimension.BUDGET,
                st,
                f"Budget provided by lead: ${f.budget_usd:,.0f}",
                Provenance.USER_PROVIDED,
                why,
                None if st == BantStatus.CONFIRMED else "Clarify whether budget is flexible.",
            )
        )

    # Authority
    title_hit = bool(f.job_title and any(t in f.job_title.lower() for t in icp.relevant_titles))
    if f.is_decision_maker is True:
        items.append(
            BantItem(
                BantDimension.AUTHORITY,
                BantStatus.CONFIRMED,
                "Marked as decision-maker in lead data",
                Provenance.USER_PROVIDED,
                "Lead data states this contact decides.",
            )
        )
    elif title_hit:
        items.append(
            BantItem(
                BantDimension.AUTHORITY,
                BantStatus.PARTIALLY_CONFIRMED,
                f"Job title: {f.job_title}",
                Provenance.USER_PROVIDED,
                "Title typically carries buying authority, but it is not confirmed.",
                "Confirm who signs off on this purchase.",
            )
        )
    elif f.is_decision_maker is False:
        items.append(
            BantItem(
                BantDimension.AUTHORITY,
                BantStatus.NOT_MATCHED,
                "Marked as NOT a decision-maker",
                Provenance.USER_PROVIDED,
                "Contact is not the decision-maker.",
                "Ask who the decision-maker is.",
            )
        )
    elif f.job_title:
        items.append(
            BantItem(
                BantDimension.AUTHORITY,
                BantStatus.PARTIALLY_CONFIRMED,
                f"Job title: {f.job_title}",
                Provenance.USER_PROVIDED,
                "Role may be an influencer; authority is unconfirmed.",
                "Ask who makes the final decision.",
            )
        )
    else:
        items.append(
            BantItem(
                BantDimension.AUTHORITY,
                BantStatus.UNKNOWN,
                None,
                Provenance.UNKNOWN,
                "No title or decision role provided.",
                "Find out the contact's role.",
            )
        )

    # Need
    if f.requirements:
        svcs = matched_services(f, icp)
        snippet = f.requirements[:240]
        if svcs:
            items.append(
                BantItem(BantDimension.NEED, BantStatus.CONFIRMED, snippet, Provenance.USER_PROVIDED, f"Stated need maps to: {', '.join(svcs)}.")
            )
        else:
            items.append(
                BantItem(
                    BantDimension.NEED,
                    BantStatus.NOT_MATCHED,
                    snippet,
                    Provenance.USER_PROVIDED,
                    "Stated need does not map to a configured service.",
                    "Ask what problem they want solved.",
                )
            )
    else:
        items.append(
            BantItem(
                BantDimension.NEED,
                BantStatus.UNKNOWN,
                None,
                Provenance.UNKNOWN,
                "No business requirement stated.",
                "Ask what problem they are trying to solve.",
            )
        )

    # Timeline
    if f.timeline == Timeline.UNKNOWN:
        items.append(
            BantItem(
                BantDimension.TIMELINE, BantStatus.UNKNOWN, None, Provenance.UNKNOWN, "No purchase timeline provided.", "Ask when they want to start."
            )
        )
    else:
        label = f.timeline.value.replace("_", " ")
        if f.timeline in (Timeline.IMMEDIATE, Timeline.WITHIN_3_MONTHS):
            st = BantStatus.CONFIRMED
        else:
            st = BantStatus.PARTIALLY_CONFIRMED
        items.append(
            BantItem(
                BantDimension.TIMELINE,
                st,
                f"Timeline provided by lead: {label}",
                Provenance.USER_PROVIDED,
                f"Lead states a '{label}' purchase horizon.",
                None if st == BantStatus.CONFIRMED else "Clarify what would trigger a decision.",
            )
        )
    return items
