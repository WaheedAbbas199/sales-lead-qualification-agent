"""Graph wiring (single compiled graph with two entry paths).

START -> route_entry -+-> load_lead -> validate_lead -> normalize_lead -> check_duplicates -> load_icp_profile
                      |   -> collect_authorized_research -> assess_bant -> calculate_lead_score -> ai_analysis
                      |   -> validate_result -> save_evaluation -> human_review -> END        (parks, awaiting a human)
                      |
                      +-> check_approval -+-> approved: prepare_outreach_draft is gated by the DB approval check
                                          +-> rejected / revision_requested / pending -> END
Any node failure routes to `fail`.
"""

from langgraph.graph import END, START, StateGraph

from app.agents.nodes.qualification_nodes import QualificationNodes
from app.agents.state import QualificationState

RECURSION_LIMIT = 40


def route_entry(state: QualificationState) -> str:
    return "check_approval" if state.get("resume") else "load_lead"


def route_after_approval_check(state: QualificationState) -> str:
    if state.get("status") == "failed":
        return "fail"
    return {"approved": "finalize_approved", "rejected": "finalize_rejected", "revision_requested": "finalize_revision"}.get(
        state.get("approval_status", ""), "pending_guard"
    )


def _ok_or_fail(next_node: str):
    def route(state: QualificationState) -> str:
        return "fail" if state.get("status") == "failed" else next_node

    return route


def build_graph(nodes: QualificationNodes):
    g = StateGraph(QualificationState)
    for name, fn in {
        "load_lead": nodes.load_lead,
        "validate_lead": nodes.validate_lead,
        "normalize_lead": nodes.normalize_lead,
        "check_duplicates": nodes.check_duplicates,
        "load_icp_profile": nodes.load_icp_profile,
        "collect_authorized_research": nodes.collect_research,
        "assess_bant": nodes.assess_bant,
        "calculate_lead_score": nodes.calculate_score,
        "ai_analysis": nodes.ai_analysis,
        "validate_result": nodes.validate_result,
        "save_evaluation": nodes.save_evaluation,
        "human_review": nodes.human_review,
        "check_approval": nodes.check_approval,
        "prepare_outreach_draft": nodes.prepare_outreach_draft,
        "finalize_approved": nodes.finalize_approved,
        "finalize_rejected": nodes.finalize_rejected,
        "finalize_revision": nodes.finalize_revision,
        "pending_guard": nodes.pending_guard,
        "fail": nodes.fail,
    }.items():
        g.add_node(name, fn)

    g.add_conditional_edges(START, route_entry, {"check_approval": "check_approval", "load_lead": "load_lead"})
    chain = [
        "load_lead",
        "validate_lead",
        "normalize_lead",
        "check_duplicates",
        "load_icp_profile",
        "collect_authorized_research",
        "assess_bant",
        "calculate_lead_score",
        "ai_analysis",
        "validate_result",
        "save_evaluation",
        "human_review",
    ]
    for cur, nxt in zip(chain, chain[1:] + ["__end__"], strict=True):
        target = END if nxt == "__end__" else nxt
        g.add_conditional_edges(cur, _ok_or_fail(nxt), {nxt: target, "fail": "fail"})
    g.add_conditional_edges(
        "check_approval",
        route_after_approval_check,
        {
            "finalize_approved": "finalize_approved",
            "finalize_rejected": "finalize_rejected",
            "finalize_revision": "finalize_revision",
            "pending_guard": "pending_guard",
            "fail": "fail",
        },
    )
    # Approved path: finalize status first, then the (approval-gated) draft tool, then end.
    g.add_conditional_edges(
        "finalize_approved", _ok_or_fail("prepare_outreach_draft"), {"prepare_outreach_draft": "prepare_outreach_draft", "fail": "fail"}
    )
    g.add_edge("prepare_outreach_draft", END)
    for terminal in ("finalize_rejected", "finalize_revision", "pending_guard", "fail"):
        g.add_edge(terminal, END)
    return g.compile()
