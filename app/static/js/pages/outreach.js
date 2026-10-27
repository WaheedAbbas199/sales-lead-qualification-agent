import { api, ApiError } from "../api.js";
import { chip, clear, field, fmtDate, fmtDay, h, modal, pretty, toast } from "../ui.js";

export function editDraftDialog(d, done) {
  const subject = h("input", { value: d.subject, maxlength: 300 }), body = h("textarea", { class: "tall" }, d.body), fu = h("input", { type: "date", value: d.follow_up_date || "" });
  body.rows = 12;
  modal({ title: "Edit draft", body: h("div", {}, field("Subject", subject), field("Body", body), field("Follow-up date", fu)),
    actions: [{ label: "Cancel", onClick: (c) => c() }, { label: "Save", class: "primary", onClick: async (close) => {
      try { await api(`/drafts/${d.id}`, { method: "PATCH", body: { subject: subject.value, body: body.value, follow_up_date: fu.value || null } }); close(); toast("Draft saved"); done(); }
      catch (ex) { toast(ex.message, "error"); }
    } }] });
}

export function draftCard(d, reload) {
  return h("div", { class: "card" },
    h("div", { class: "actions" }, h("h3", {}, d.company_name ? h("a", { href: `#/lead/${d.lead_id}` }, `${d.company_name} · ${d.lead_name}`) : "Draft"), chip(d.status), h("span", { class: "chip" }, pretty(d.draft_type)),
      h("span", { class: "prov" }, `by ${d.generated_by}`)),
    h("div", { class: "small muted" }, `Subject: ${d.subject}`), h("div", { class: "draft" }, d.body),
    d.evidence_references.length ? h("p", { class: "small muted" }, "Cites the lead's own words: ", d.evidence_references.map((r) => `“${r}”`).join(", ")) : h("p", { class: "small muted" }, "Makes no claim about the prospect beyond what is in the lead record."),
    h("div", { class: "small muted" }, `Created ${fmtDate(d.created_at)} · follow-up ${fmtDay(d.follow_up_date)}${d.sent_manually_at ? " · marked sent " + fmtDate(d.sent_manually_at) : ""}`),
    d.status === "draft" ? h("div", { class: "actions" },
      h("button", { onclick: async () => { try { await navigator.clipboard.writeText(`Subject: ${d.subject}\n\n${d.body}`); toast("Copied to clipboard"); } catch { toast("Copy failed — select the text manually", "error"); } } }, "Copy"),
      h("button", { onclick: () => editDraftDialog(d, reload) }, "Edit"),
      h("button", { class: "primary", onclick: async () => { try { await api(`/drafts/${d.id}/mark-sent`, { method: "POST" }); toast("Recorded as sent manually"); reload(); } catch (ex) { toast(ex instanceof ApiError ? ex.message : "Failed", "error"); } } }, "Mark as sent manually")) : null);
}

export async function renderOutreach(main) {
  let status = "";
  const list = h("div", { class: "stack" });
  const load = async () => {
    const drafts = await api(`/drafts${status ? `?status=${status}` : ""}`);
    clear(list).append(...(drafts.length ? drafts.map((d) => draftCard(d, load)) : [h("div", { class: "card empty" }, "No drafts yet. Generate one from a lead page.")]));
  };
  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Outreach"), h("p", {}, "Drafts only. This app never sends email — copy a draft, send it yourself, then mark it as sent."))),
    h("div", { class: "toolbar" }, h("select", { "aria-label": "Filter drafts", onchange: (e) => { status = e.target.value; load(); } }, h("option", { value: "" }, "All drafts"), h("option", { value: "draft" }, "Drafts"), h("option", { value: "sent_manually" }, "Sent manually"))), list);
  await load();
}
