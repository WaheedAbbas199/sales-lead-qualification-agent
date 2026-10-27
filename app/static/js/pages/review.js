import { api, ApiError, session } from "../api.js";
import { chip, fmtDate, h, modal, toast, clear } from "../ui.js";

function decisionDialog(ap, decision, done) {
  const note = h("textarea", { "aria-label": "Comment", placeholder: decision === "approved" ? "Optional note" : "Required: explain your decision", maxlength: 2000 });
  const labels = { approved: "Approve", rejected: "Reject", revision_requested: "Request revision" };
  modal({ title: `${labels[decision]} · ${ap.company_name}`, body: h("div", {},
    h("p", { class: "muted small" }, decision === "approved" ? "Approving lets the workflow set the final status and prepare a draft (still never sent automatically)." : "No status change or draft will be applied."), note),
    actions: [{ label: "Cancel", onClick: (c) => c() }, { label: labels[decision], class: decision === "rejected" ? "danger" : "primary", onClick: async (close) => {
      try { await api(`/approvals/${ap.id}/decision`, { method: "POST", body: { decision, comment: note.value || null } }); close(); toast(`${labels[decision]} recorded`); done(); }
      catch (ex) { toast(ex instanceof ApiError ? ex.message : "Failed", "error"); }
    } }] });
}

export async function renderReview(main) {
  const body = h("div", { class: "stack" });
  const canReview = session.user.role === "reviewer" || session.user.role === "admin";
  let tab = "pending";
  const load = async () => {
    const list = await api(`/approvals?status=${tab}`);
    clear(body).append(...(list.length ? list.map((ap) => h("div", { class: "card" },
      h("div", { class: "actions" }, h("h2", {}, h("a", { href: `#/lead/${ap.lead_id}` }, `${ap.company_name} · ${ap.lead_name}`)), chip(ap.status),
        ap.priority ? chip(ap.priority) : null, ap.suspicious_content ? h("span", { class: "chip warn" }, "possible prompt injection") : null),
      h("p", { class: "small muted" }, `Requested ${fmtDate(ap.created_at)} · score ${ap.score == null ? "—" : Math.round(ap.score)}/100`),
      ap.ai_summary ? h("p", {}, h("b", {}, "AI summary (proposal): "), ap.ai_summary) : h("p", { class: "muted" }, "No AI summary available (deterministic scoring only)."),
      ap.missing_information.length ? h("div", {}, h("b", {}, "Missing information"), h("ul", { class: "plain" }, ap.missing_information.slice(0, 6).map((m) => h("li", {}, m)))) : null,
      ap.status === "pending" ? h("div", { class: "actions" },
        h("button", { class: "primary", disabled: !canReview, onclick: () => decisionDialog(ap, "approved", load) }, "Approve"),
        h("button", { disabled: !canReview, onclick: () => decisionDialog(ap, "revision_requested", load) }, "Request revision"),
        h("button", { class: "danger", disabled: !canReview, onclick: () => decisionDialog(ap, "rejected", load) }, "Reject"),
        canReview ? null : h("span", { class: "muted small" }, "Only reviewers and admins can decide.")) : h("p", { class: "small" }, `Decision: ${ap.status}${ap.comment ? " — " + ap.comment : ""} (${fmtDate(ap.decided_at)})`)))
      : [h("div", { class: "card empty" }, tab === "pending" ? "Nothing waiting for review." : "No decisions yet.")]));
  };
  const tabs = h("div", { class: "toolbar" }, ["pending", "approved", "rejected", "revision_requested"].map((t) => h("button", { class: t === tab ? "primary" : "", onclick: (e) => { tab = t; tabs.querySelectorAll("button").forEach((b) => b.classList.remove("primary")); e.target.classList.add("primary"); load(); } }, t.replace("_", " "))));
  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Review queue"), h("p", {}, "Every qualification waits here for a human decision before any status change or draft."))), tabs, body);
  await load();
}
