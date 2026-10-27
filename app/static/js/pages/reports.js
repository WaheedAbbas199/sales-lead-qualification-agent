import { api } from "../api.js";
import { bar, h, pretty } from "../ui.js";

function dist(title, data) {
  const entries = Object.entries(data || {});
  const max = Math.max(1, ...entries.map(([, v]) => v));
  return h("div", { class: "card" }, h("h2", {}, title),
    entries.length ? h("div", { class: "stack" }, entries.map(([k, v]) => h("div", {}, h("div", { class: "actions" }, h("span", {}, pretty(k)), h("b", { class: "num" }, v)), bar((v / max) * 100))))
      : h("p", { class: "muted" }, "No data yet."));
}

export async function renderReports(main) {
  const r = await api("/dashboard/reports");
  main.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Reports"), h("p", {}, "Descriptive metrics about the qualification process."))),
    h("div", { class: "banner" }, r.note),
    h("div", { class: "grid g2" },
      dist("Lead distribution by priority", r.priority_distribution), dist("Qualification status", r.status_distribution),
      dist("Lead sources", r.lead_sources), dist("Outreach drafts", r.follow_up_activity), dist("Review outcomes", r.approval_outcomes),
      dist("AI analysis status", r.ai_status_distribution)),
    h("div", { class: "card" }, h("h2", {}, "Evaluation history (last 14 days)"),
      r.evaluation_history.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Day", "Evaluations", "Average score"].map((x) => h("th", {}, x)))),
        h("tbody", {}, r.evaluation_history.map((e) => h("tr", {}, h("td", {}, e.day), h("td", { class: "num" }, e.evaluations), h("td", { class: "num" }, e.avg_score))))))
        : h("p", { class: "muted" }, "No evaluations yet.")));
}
