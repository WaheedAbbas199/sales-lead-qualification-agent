import { api, ApiError, session } from "../api.js";
import { clear, confirmDialog, field, fmtDate, h, toast } from "../ui.js";

const LEAD_FIELDS = ["industry", "company_size", "country", "job_title", "requirements", "budget_usd", "timeline", "website", "email"];
const csv = (a) => (a || []).join(", ");
const list = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);

export async function renderIcp(main) {
  const [icp, versions, crit] = await Promise.all([api("/icp"), api("/icp/versions"), api("/icp/criteria")]);
  const isAdmin = session.user.role === "admin";
  const c = icp.config;
  const dis = { disabled: !isAdmin };
  const text = (name, val, extra = {}) => h("input", { name, value: val ?? "", ...dis, ...extra });
  const wInputs = Object.fromEntries(crit.criteria.map((k) => [k.name, h("input", { type: "number", min: 0, step: "any", value: c.weights[k.name], ...dis, "aria-label": `${k.label} weight` })]));
  const pct = h("p", { class: "small muted" });
  const updPct = () => { const t = Object.values(wInputs).reduce((s, i) => s + (Number(i.value) || 0), 0); pct.textContent = t > 0 ? "Normalised: " + crit.criteria.map((k) => `${k.label.split(" (")[0]} ${((Number(wInputs[k.name].value) || 0) / t * 100).toFixed(0)}%`).join(" · ") : "Weights must not all be zero"; };
  Object.values(wInputs).forEach((i) => i.addEventListener("input", updPct)); updPct();

  const fields = { description: h("textarea", { name: "description", ...dis }, c.description), industries: text("ti", csv(c.target_industries)), countries: text("tc", csv(c.target_countries)), regions: text("tr", csv(c.target_regions)),
    titles: text("tt", csv(c.relevant_titles)), problems: h("textarea", { ...dis }, csv(c.supported_problems)), smin: text("smin", c.company_size_min, { type: "number", min: 0 }), smax: text("smax", c.company_size_max, { type: "number", min: 0 }),
    minBudget: text("mb", c.min_budget_usd, { type: "number", min: 0 }), minScore: text("ms", c.min_qualifying_score, { type: "number", min: 0, max: 100 }), high: text("hi", c.thresholds.high_min, { type: "number", min: 0, max: 100 }), med: text("me", c.thresholds.medium_min, { type: "number", min: 0, max: 100 }),
    exInd: text("ei", csv(c.disqualification.excluded_industries)), exCtry: text("ec", csv(c.disqualification.excluded_countries)), hardBudget: text("hb", c.disqualification.hard_min_budget_usd, { type: "number", min: 0 }),
    optOut: h("input", { type: "checkbox", checked: c.disqualification.disqualify_on_opt_out, ...dis }) };
  const reqBoxes = LEAD_FIELDS.map((f) => [f, h("input", { type: "checkbox", checked: c.required_fields.includes(f), ...dis })]);
  const svcRows = h("div");
  const svcRow = (s = { name: "", description: "", keywords: [], min_budget_usd: "" }) => {
    const row = h("div", { class: "svc" }, h("input", { placeholder: "Service name", value: s.name, ...dis, "aria-label": "Service name" }), h("input", { placeholder: "Description", value: s.description, ...dis, "aria-label": "Description" }),
      h("input", { placeholder: "keywords, comma separated", value: csv(s.keywords), ...dis, "aria-label": "Keywords" }), h("input", { type: "number", min: 0, placeholder: "Min $", value: s.min_budget_usd ?? "", ...dis, "aria-label": "Minimum budget" }),
      isAdmin ? h("button", { class: "sm ghost", type: "button", onclick: () => row.remove(), "aria-label": "Remove service" }, "✕") : null);
    return row;
  };
  c.services.forEach((s) => svcRows.append(svcRow(s)));
  const num = (i) => (i.value === "" ? null : Number(i.value));

  const save = async () => {
    const services = [...svcRows.children].map((r) => { const i = r.querySelectorAll("input"); return { name: i[0].value.trim(), description: i[1].value.trim(), keywords: list(i[2].value), min_budget_usd: i[3].value === "" ? null : Number(i[3].value) }; }).filter((s) => s.name);
    const config = { description: fields.description.value, target_industries: list(fields.industries.value), company_size_min: num(fields.smin), company_size_max: num(fields.smax), target_countries: list(fields.countries.value),
      target_regions: list(fields.regions.value), relevant_titles: list(fields.titles.value), supported_problems: list(fields.problems.value), services, min_budget_usd: num(fields.minBudget), min_qualifying_score: Number(fields.minScore.value),
      required_fields: reqBoxes.filter(([, b]) => b.checked).map(([f]) => f), weights: Object.fromEntries(Object.entries(wInputs).map(([k, i]) => [k, Number(i.value) || 0])),
      thresholds: { high_min: Number(fields.high.value), medium_min: Number(fields.med.value) },
      disqualification: { excluded_industries: list(fields.exInd.value), excluded_countries: list(fields.exCtry.value), hard_min_budget_usd: num(fields.hardBudget), disqualify_on_opt_out: fields.optOut.checked } };
    try { const r = await api("/icp", { method: "PUT", body: { config } }); toast(`Saved as version ${r.version}. Existing evaluations keep the version they used.`); renderPage(); }
    catch (ex) { if (ex instanceof ApiError && ex.status === 422) toast(ex.details.map((d) => `${d.field}: ${d.message}`).join(" | "), "error"); else toast(ex.message, "error"); }
  };
  const renderPage = () => { clear(main); renderIcp(main); };

  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "ICP settings"), h("p", {}, `Active: ${icp.name} v${icp.version} · saved ${fmtDate(icp.created_at)}. Thresholds are starting points, not industry benchmarks, and a score is not a conversion probability.`)),
    isAdmin ? h("div", { class: "actions" }, h("button", { onclick: async () => { if (await confirmDialog("Recalculate all leads?", "Creates a new evaluation for every lead using the active ICP. History is kept.", "Recalculate")) { const r = await api("/icp/recalculate", { method: "POST" }); toast(`Recalculated ${r.recalculated} leads`); } } }, "Recalculate all leads"), h("button", { class: "primary", onclick: save }, "Save as new version")) : h("span", { class: "chip" }, "Read-only: admin required")),
    h("div", { class: "card" }, h("h2", {}, "Ideal customer"), field("Description", fields.description),
      h("div", { class: "form-grid" }, field("Target industries", fields.industries, { hint: "comma separated" }), field("Target countries", fields.countries), field("Target regions", fields.regions), field("Relevant job titles", fields.titles),
        field("Company size min", fields.smin), field("Company size max", fields.smax)), field("Supported business problems (keywords)", fields.problems)),
    h("div", { class: "card" }, h("h2", {}, "Service offerings"), svcRows, isAdmin ? h("button", { type: "button", onclick: () => svcRows.append(svcRow()) }, "+ Add service") : null),
    h("div", { class: "card" }, h("h2", {}, "Scoring weights"), h("div", { class: "weights" }, crit.criteria.map((k) => field(k.label, wInputs[k.name]))), pct,
      h("div", { class: "form-grid" }, field("Soft minimum budget (USD)", fields.minBudget), field("Min score to qualify", fields.minScore), field("High priority ≥", fields.high), field("Medium priority ≥", fields.med)),
      h("h3", {}, "Required evidence"), h("div", { class: "actions" }, reqBoxes.map(([f, b]) => h("label", { class: "small" }, b, ` ${f}`)))),
    h("div", { class: "card" }, h("h2", {}, "Disqualification rules"), h("p", { class: "small muted" }, "Only applied when the lead explicitly provides conflicting data. Missing data never disqualifies."),
      h("div", { class: "form-grid" }, field("Excluded industries", fields.exInd), field("Excluded countries", fields.exCtry), field("Hard minimum budget (USD)", fields.hardBudget)), h("label", {}, fields.optOut, " Disqualify contacts who opted out")),
    h("div", { class: "card" }, h("h2", {}, "Version history"), h("ul", { class: "plain" }, versions.map((v) => h("li", {}, `v${v.version} · ${fmtDate(v.created_at)}${v.is_active ? " · active" : ""}`)))));
}
