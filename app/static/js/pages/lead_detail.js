import { api, ApiError, session } from "../api.js";
import { bar, chip, clear, confirmDialog, fmtDate, fmtDay, gauge, h, modal, money, pretty, prov, safeUrl, toast } from "../ui.js";
import { openLeadForm } from "./leads.js";
import { draftCard } from "./outreach.js";

const DRAFT_TYPES = ["introduction", "discovery_meeting", "follow_up", "missing_info_request"];

function section(title, ...kids) { return h("section", { class: "card", "aria-label": title }, h("h2", {}, title), ...kids); }

function breakdown(ev) {
  return h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Criterion", "Status", "Points", "Why"].map((x) => h("th", { scope: "col" }, x)))),
    h("tbody", {}, ev.breakdown.map((c) => h("tr", {}, h("td", {}, c.label, h("div", { class: "muted small" }, `weight ${c.weight_pct.toFixed(1)}%`)), h("td", {}, chip(c.status)),
      h("td", {}, h("div", { class: "num" }, `${c.points.toFixed(1)} / ${c.max_points.toFixed(1)}`), bar(c.max_points ? (c.points / c.max_points) * 100 : 0)), h("td", {}, c.reason))))));
}

function bantCards(ev) {
  const rules = ev.bant.filter((b) => b.origin === "rules"), ai = ev.bant.filter((b) => b.origin === "ai");
  return h("div", {},
    h("div", { class: "grid g4" }, rules.map((b) => h("div", { class: `card bant ${b.status}` }, h("div", { class: "actions" }, h("h3", {}, pretty(b.dimension)), chip(b.status)),
      h("p", { class: "small" }, b.rationale), b.evidence_text ? h("p", { class: "small" }, prov(b.provenance), " ", `“${b.evidence_text}”`) : h("p", { class: "small muted" }, "No evidence — unknown stays unknown."),
      b.clarification_needed ? h("p", { class: "small" }, h("b", {}, "Ask: "), b.clarification_needed) : null))),
    ai.length ? h("div", {}, h("h3", {}, "AI suggestions (never override the rules above)"), h("div", { class: "grid g4" }, ai.map((b) => h("div", { class: "card" }, h("b", {}, pretty(b.dimension)), " ", chip(b.status), prov("ai_inferred"),
      h("p", { class: "small" }, b.rationale), b.evidence_text ? h("p", { class: "small muted" }, `Quote: “${b.evidence_text}”`) : null)))) : null);
}

function aiSection(ev) {
  const r = ev.ai_report;
  const msg = { not_run: "AI analysis has not been run for this evaluation (deterministic score only).", unavailable: "AI provider was unavailable (timeout or rate limit). The deterministic score is unaffected.",
    malformed: "AI returned an invalid response, so it was discarded. The deterministic score is unaffected.", not_configured: "AI provider is not configured. Set LLM_PROVIDER=gemini and GEMINI_API_KEY." }[ev.ai_status];
  if (!r) return section("AI explanation", h("p", { class: "muted" }, msg || ""));
  return section("AI explanation (a proposal, not a decision)",
    r.suspicious_input_detected ? h("div", { class: "banner bad", role: "alert" }, "Lead or research text contained instruction-like content. It was treated as data only; review carefully.") : null,
    h("p", {}, r.summary),
    h("div", { class: "grid g2" },
      h("div", {}, h("h3", {}, "Business needs"), h("ul", { class: "plain" }, r.business_needs.map((n) => h("li", {}, n))), h("h3", {}, "Mapped services"), h("p", {}, r.mapped_services.join(", ") || "—")),
      h("div", {}, h("h3", {}, "Recommended follow-up questions"), h("ul", { class: "plain" }, r.recommended_questions.map((n) => h("li", {}, n))))),
    h("p", {}, h("b", {}, "Next action: "), pretty(r.recommended_next_action), " · ", h("b", {}, "Evidence sufficiency: "), `${Math.round(r.confidence * 100)}%`,
      h("span", { class: "muted small" }, " (how much evidence supports this assessment — not a chance of winning the deal)")));
}

export async function renderLeadDetail(main, id, ctx) {
  const holder = h("div", { class: "stack" });
  main.append(holder);
  const canWrite = ["sales", "reviewer", "admin"].includes(session.user.role);

  const load = async () => {
    const d = await api(`/leads/${id}/detail`);
    const { lead, evaluation: ev } = d;
    const activeWf = d.workflows.find((w) => ["queued", "running"].includes(w.status));
    if (activeWf) ctx.poll(load, 1500); else ctx.stopPolling();
    const run = async (fn, okMsg) => { try { await fn(); if (okMsg) toast(okMsg); await load(); } catch (ex) { toast(ex instanceof ApiError ? ex.message : "Failed", "error"); } };
    const detail = (label, val) => [h("dt", {}, label), h("dd", {}, val ?? "—")];
    clear(holder).append(
      h("div", { class: "page-head" }, h("div", {}, h("a", { href: "#/leads", class: "small" }, "← All leads"), h("h1", {}, `${lead.first_name} ${lead.last_name}`), h("p", {}, `${lead.company_name}${lead.job_title ? " · " + lead.job_title : ""}`)),
        canWrite ? h("div", { class: "actions" },
          h("button", { class: "amber", disabled: !!activeWf || lead.status === "archived", onclick: () => run(() => api(`/leads/${id}/qualify`, { method: "POST" }), "Qualification started") },
            activeWf ? [h("span", { class: "spinner" }), " Running…"] : "Run AI qualification"),
          h("button", { onclick: () => run(() => api(`/leads/${id}/score`, { method: "POST" }), "Rescored (deterministic)") }, "Re-score only"),
          h("button", { onclick: () => openLeadForm(lead, load) }, "Edit"),
          h("button", { onclick: () => draftDialog(id, load) }, "New draft"),
          lead.status === "archived" ? h("button", { onclick: () => run(() => api(`/leads/${id}/restore`, { method: "POST" }), "Restored") }, "Restore")
            : h("button", { class: "ghost", onclick: async () => { if (await confirmDialog("Archive lead?", "The lead is hidden from lists but its history is kept.", "Archive", true)) run(() => api(`/leads/${id}/archive`, { method: "POST" }), "Archived"); } }, "Archive")) : null),
      lead.suspicious_content ? h("div", { class: "banner bad", role: "alert" }, "This lead's text contains instruction-like content (possible prompt injection). It is treated strictly as data and always needs human review.") : null,
      d.pending_approval ? h("div", { class: "banner" }, "Waiting for human review. ", h("a", { href: "#/review" }, "Open the review queue")) : null,
      section("Qualification summary",
        h("div", { class: "hero" }, gauge(ev?.total_score ?? lead.latest_score, ev?.priority ?? lead.priority),
          h("div", {}, h("div", { class: "actions" }, chip(lead.status), ev ? chip(ev.priority) : null, ev?.disqualified ? h("span", { class: "chip warn" }, "disqualified by rule") : null),
            ev ? h("p", { class: "small muted" }, `Evaluated ${fmtDate(ev.created_at)} · ICP v${ev.icp_version} · ${ev.engine_version} · ${ev.kind === "full" ? "full workflow" : "score only"}`) : h("p", { class: "muted" }, "Not scored yet — use “Re-score only” or “Run AI qualification”."),
            ev?.disqualification_reasons.length ? h("ul", { class: "plain" }, ev.disqualification_reasons.map((r) => h("li", {}, r))) : null))),
      h("div", { class: "grid g2" },
        section("Contact & company", h("dl", { class: "kv" }, detail("Email", lead.email), detail("Website", lead.website), detail("Industry", lead.industry), detail("Location", [lead.region, lead.country].filter(Boolean).join(", ") || null),
          detail("Company size", lead.company_size), detail("Decision maker", lead.is_decision_maker == null ? "Unknown" : lead.is_decision_maker ? "Yes" : "No"), detail("Budget", money(lead.budget_usd)), detail("Timeline", pretty(lead.timeline)),
          detail("Consent", pretty(lead.consent)), detail("Source", lead.source_name), detail("Follow-up", fmtDay(lead.follow_up_date)))),
        section("Stated requirements", h("p", { class: "draft" }, lead.requirements || "None provided."), ev?.missing_information.length ? [h("h3", {}, "Missing information"), h("ul", { class: "plain" }, ev.missing_information.map((m) => h("li", {}, m)))] : null)),
      ev ? section("Score breakdown", breakdown(ev)) : null,
      ev ? section("BANT assessment", bantCards(ev)) : null,
      ev ? aiSection(ev) : null,
      ev ? section("Evidence & sources", ev.evidence.length ? h("ul", { class: "plain" }, ev.evidence.map((e) => h("li", {}, prov(e.provenance), " ", e.statement, " ",
        safeUrl(e.source_url) ? h("a", { href: safeUrl(e.source_url), target: "_blank", rel: "noopener noreferrer" }, "source") : null, e.retrieved_at ? h("span", { class: "muted small" }, ` retrieved ${fmtDate(e.retrieved_at)}`) : null)))
        : h("p", { class: "muted" }, "No external evidence. Research is optional and was not available or not run.")) : null,
      section("Outreach drafts", d.drafts.length ? d.drafts.map((x) => draftCard(x, load)) : h("p", { class: "muted" }, "No drafts yet.")),
      h("div", { class: "grid g2" },
        section("Qualification history", d.history.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["When", "Type", "Score", "ICP", "AI"].map((x) => h("th", {}, x)))),
          h("tbody", {}, d.history.map((x) => h("tr", {}, h("td", {}, fmtDate(x.created_at)), h("td", {}, x.kind === "full" ? "workflow" : "score"), h("td", { class: "num" }, Math.round(x.score)), h("td", {}, `v${x.icp_version}`), h("td", {}, x.ai_status)))))) : h("p", { class: "muted" }, "No evaluations yet.")),
        section("Workflow runs", d.workflows.length ? d.workflows.map((w) => h("details", {}, h("summary", {}, `${fmtDate(w.created_at)} · `, chip(w.status), w.error ? ` ${w.error}` : ""),
          h("ol", { class: "small" }, w.trace.map((t) => h("li", {}, `${t.node} — ${t.outcome} (${t.ms} ms)`))))) : h("p", { class: "muted" }, "Never run."))),
      section("Activity timeline", h("ul", { class: "timeline" }, d.activities.map((a) => h("li", {}, h("div", {}, a.message), h("div", { class: "muted small" }, `${fmtDate(a.created_at)} · ${a.kind}`))))));
  };
  await load();
}

function draftDialog(leadId, done) {
  const type = h("select", { "aria-label": "Draft type" }, DRAFT_TYPES.map((t) => h("option", { value: t }, pretty(t))));
  const cta = h("input", { placeholder: "e.g. a 15-minute intro call (optional)", maxlength: 200, "aria-label": "Call to action" });
  modal({ title: "Generate outreach draft", body: h("div", {}, h("p", { class: "muted small" }, "Drafts only reference what the lead stated. Nothing is sent."), h("div", { class: "field" }, type), h("div", { class: "field" }, cta)),
    actions: [{ label: "Cancel", onClick: (c) => c() }, { label: "Generate", class: "primary", onClick: async (close) => {
      try { await api(`/leads/${leadId}/drafts`, { method: "POST", body: { draft_type: type.value, call_to_action: cta.value || null } }); close(); toast("Draft created"); done(); }
      catch (ex) { toast(ex.message, "error"); }
    } }] });
}
