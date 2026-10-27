import { api, ApiError, qs, session } from "../api.js";
import { chip, clear, download, field, fmtDay, h, modal, money, setFieldErrors, table, toast } from "../ui.js";

const TIMELINES = ["unknown", "immediate", "within_3_months", "within_6_months", "exploring"];
const CONSENTS = ["unknown", "granted", "opted_out"];
const STATUSES = ["new", "qualifying", "pending_review", "qualified", "nurture", "disqualified", "needs_revision"];

export function openLeadForm(lead, onSaved) {
  const v = lead || {};
  const inp = (name, type = "text", extra = {}) => h("input", { name, type, value: v[name] ?? "", ...extra });
  const sel = (name, options, cur) => h("select", { name }, options.map((o) => h("option", { value: o, selected: o === cur }, o.replace(/_/g, " "))));
  const dm = h("select", { name: "is_decision_maker" }, [["", "Unknown"], ["true", "Yes"], ["false", "No"]].map(([val, lab]) =>
    h("option", { value: val, selected: String(v.is_decision_maker ?? "") === val }, lab)));
  const form = h("form", { novalidate: true },
    h("div", { class: "form-grid" },
      field("First name *", inp("first_name", "text", { required: true, maxlength: 100 })), field("Last name", inp("last_name", "text", { maxlength: 100 })),
      field("Company *", inp("company_name", "text", { required: true, maxlength: 200 })), field("Business email", inp("email", "email")),
      field("Website", inp("website"), { hint: "domain or URL" }), field("Industry", inp("industry"), { hint: "e.g. HVAC" }),
      field("Country", inp("country")), field("Region / state", inp("region")),
      field("Company size", inp("company_size", "number", { min: 1 }), { hint: "employees" }), field("Job title", inp("job_title")),
      field("Decision maker?", dm), field("Budget (USD)", inp("budget_usd", "number", { min: 0, step: "any" }), { hint: "leave blank if unknown" }),
      field("Purchase timeline", sel("timeline", TIMELINES, v.timeline || "unknown")), field("Contact consent", sel("consent", CONSENTS, v.consent || "unknown")),
      field("Source", inp("source", "text", { value: v.source_name ?? "" })), field("Follow-up date", inp("follow_up_date", "date"))),
    field("Business requirements", h("textarea", { name: "requirements", maxlength: 5000 }, v.requirements ?? ""), { hint: "in the lead's own words if possible" }));
  const m = modal({ title: lead ? "Edit lead" : "New lead", body: form, actions: [
    { label: "Cancel", onClick: (c) => c() },
    { label: lead ? "Save changes" : "Create lead", class: "primary", onClick: async (close) => {
      const data = {};
      new FormData(form).forEach((val, k) => { data[k] = val; });
      ["company_size", "budget_usd"].forEach((k) => { data[k] = data[k] === "" ? null : Number(data[k]); });
      data.is_decision_maker = data.is_decision_maker === "" ? null : data.is_decision_maker === "true";
      ["email", "website", "industry", "country", "region", "job_title", "requirements", "source", "follow_up_date", "last_name"].forEach((k) => { if (data[k] === "") data[k] = lead ? null : (k === "last_name" ? "" : null); });
      if (!lead) Object.keys(data).forEach((k) => { if (data[k] === null && k !== "is_decision_maker") delete data[k]; });
      try {
        const res = lead ? await api(`/leads/${lead.id}`, { method: "PATCH", body: data }) : await api("/leads", { method: "POST", body: data });
        close();
        if (!lead && res.possible_duplicates?.length) toast(`Saved. Possible duplicate: ${res.possible_duplicates[0].full_name} (${res.possible_duplicates[0].reason}).`);
        else toast(lead ? "Lead updated" : "Lead created");
        onSaved?.(res.lead || res);
      } catch (ex) {
        if (ex instanceof ApiError && ex.status === 422) setFieldErrors(form, ex.details); else toast(ex.message, "error");
      }
    } }] });
  return m;
}

function importDialog(onDone) {
  const file = h("input", { type: "file", accept: ".csv,text/csv", "aria-label": "CSV file" });
  const out = h("div");
  modal({ title: "Import leads from CSV", body: h("div", {},
    h("p", { class: "muted small" }, "Required columns: first_name, company_name. Max 2 MB. Rows are validated; duplicates by email are skipped, never overwritten."),
    h("div", { class: "actions" }, h("button", { onclick: async () => { const r = await api("/leads/import/template", { raw: true }); download("lead_import_template.csv", await r.text()); } }, "Download template")),
    h("div", { class: "field" }, file), out),
    actions: [{ label: "Close", onClick: (c) => c() }, { label: "Upload", class: "primary", onClick: async () => {
      if (!file.files[0]) return toast("Choose a CSV file first", "error");
      const fd = new FormData(); fd.append("file", file.files[0]);
      clear(out).append(h("span", { class: "spinner" }));
      try {
        const r = await api("/leads/import", { method: "POST", form: fd });
        clear(out).append(h("div", { class: "banner ok" }, `${r.created} created · ${r.skipped_duplicates} duplicates skipped · ${r.rejected} rejected · ${r.possible_duplicates} possible duplicates flagged`),
          r.ignored_columns.length ? h("p", { class: "small muted" }, `Ignored columns: ${r.ignored_columns.join(", ")}`) : null,
          r.errors.length ? table([{ header: "Row", render: (e) => e.row }, { header: "Problems", render: (e) => e.errors.join("; ") }], r.errors) : null,
          r.error_report_csv ? h("button", { onclick: () => download("rejected_rows.csv", r.error_report_csv) }, "Download error report") : null);
        onDone();
      } catch (ex) { clear(out).append(h("div", { class: "banner bad", role: "alert" }, ex.message)); }
    } }] });
}

export async function renderLeads(main) {
  const st = { q: "", status: "", priority: "", include_archived: false, sort: "created_at", order: "desc", page: 1, page_size: 20 };
  const canWrite = ["sales", "reviewer", "admin"].includes(session.user.role);
  const list = h("div");
  const load = async () => {
    const res = await api(`/leads${qs({ ...st, include_archived: st.include_archived || undefined })}`);
    const sortBtn = (label, key) => h("button", { onclick: () => { st.order = st.sort === key && st.order === "asc" ? "desc" : "asc"; st.sort = key; load(); },
      "aria-label": `Sort by ${label}` }, label + (st.sort === key ? (st.order === "asc" ? " ▲" : " ▼") : ""));
    const pages = Math.max(1, Math.ceil(res.total / st.page_size));
    clear(list).append(
      table([
        { header: sortBtn("Company", "company_name"), render: (l) => h("div", {}, h("a", { href: `#/lead/${l.id}` }, l.company_name), h("div", { class: "muted small" }, `${l.first_name} ${l.last_name}${l.job_title ? " · " + l.job_title : ""}`)) },
        { header: "Industry", render: (l) => l.industry || "—" },
        { header: sortBtn("Status", "status"), render: (l) => h("span", {}, chip(l.status), l.suspicious_content ? h("span", { class: "chip warn", title: "Possible instructions hidden in lead text" }, "flagged") : null) },
        { header: sortBtn("Priority", "priority"), render: (l) => (l.priority ? chip(l.priority) : "—") },
        { header: sortBtn("Score", "latest_score"), render: (l) => h("span", { class: "num" }, l.latest_score == null ? "—" : Math.round(l.latest_score)) },
        { header: "Budget", render: (l) => money(l.budget_usd) },
        { header: sortBtn("Follow-up", "follow_up_date"), render: (l) => fmtDay(l.follow_up_date) },
      ], res.items, { empty: "No leads match. Create one or import a CSV." }),
      h("div", { class: "pager" }, h("span", { class: "muted small num" }, `${res.total} lead${res.total === 1 ? "" : "s"} · page ${st.page}/${pages}`),
        h("button", { disabled: st.page <= 1, onclick: () => { st.page--; load(); } }, "Previous"), h("button", { disabled: st.page >= pages, onclick: () => { st.page++; load(); } }, "Next")));
  };
  let t;
  const search = h("input", { type: "search", placeholder: "Search name, company, email", "aria-label": "Search leads", oninput: (e) => { clearTimeout(t); t = setTimeout(() => { st.q = e.target.value; st.page = 1; load(); }, 250); } });
  const statusSel = h("select", { "aria-label": "Filter by status", onchange: (e) => { st.status = e.target.value; st.page = 1; load(); } }, h("option", { value: "" }, "All statuses"), STATUSES.map((s) => h("option", { value: s }, s.replace(/_/g, " "))));
  const prioSel = h("select", { "aria-label": "Filter by priority", onchange: (e) => { st.priority = e.target.value; st.page = 1; load(); } }, h("option", { value: "" }, "All priorities"), ["high", "medium", "low"].map((s) => h("option", { value: s }, s)));
  const arch = h("label", { class: "small" }, h("input", { type: "checkbox", style: null, onchange: (e) => { st.include_archived = e.target.checked; load(); } }), " Show archived");
  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Leads"), h("p", {}, "Search, filter and open a lead to qualify it.")),
    canWrite ? h("div", { class: "actions" }, h("button", { onclick: () => importDialog(load) }, "Import CSV"), h("button", { class: "primary", onclick: () => openLeadForm(null, load) }, "New lead")) : null),
    h("div", { class: "toolbar" }, search, statusSel, prioSel, arch), list);
  await load();
}
