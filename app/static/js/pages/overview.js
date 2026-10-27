import { api } from "../api.js";
import { fmtDate, h } from "../ui.js";

const stat = (label, value, cls = "") => h("div", { class: `card stat ${cls}` }, h("div", { class: "v" }, value), h("div", { class: "l" }, label));

export async function renderOverview(main) {
  const [stats, ready] = await Promise.all([api("/dashboard/stats"), api("/ready")]);
  const ai = ready.ai.configured ? `AI analysis: ${ready.ai.provider} connected` : "AI analysis is not configured — scoring still works, AI summaries are skipped.";
  const rs = ready.research.configured ? "Company research enabled." : "Company research is off.";
  main.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Overview"), h("p", {}, "What needs attention right now."))),
    h("div", { class: `banner ${ready.ai.configured ? "ok" : ""}` }, `${ai} ${rs} Outreach is draft-only: nothing is ever sent automatically.`),
    h("div", { class: "grid g5" },
      stat("Total leads", stats.total_leads), stat("Qualified leads", stats.qualified_leads),
      stat("High priority", stats.high_priority_leads, "hot"), stat("Awaiting review", stats.awaiting_review, "wait"),
      stat("Follow-ups due", stats.follow_ups_due, "hot")),
    h("div", { class: "card" }, h("h2", {}, "Recent activity"),
      stats.recent_activity.length
        ? h("ul", { class: "timeline" }, stats.recent_activity.map((a) => h("li", {},
            h("a", { href: `#/lead/${a.lead_id}` }, `${a.lead} · ${a.company}`), h("div", {}, a.message), h("div", { class: "muted small" }, fmtDate(a.at)))))
        : h("div", { class: "empty" }, "No activity yet. Add or import leads to get started.")));
}
