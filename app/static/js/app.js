import { api, session, setUnauthorizedHandler } from "./api.js";
import { clear, h, svg, toast } from "./ui.js";
import { renderOverview } from "./pages/overview.js";
import { renderLeads } from "./pages/leads.js";
import { renderLeadDetail } from "./pages/lead_detail.js";
import { renderReview } from "./pages/review.js";
import { renderOutreach } from "./pages/outreach.js";
import { renderIcp } from "./pages/icp.js";
import { renderReports } from "./pages/reports.js";

const root = document.getElementById("app");
const ROUTES = [
  { path: "overview", label: "Overview", render: renderOverview },
  { path: "leads", label: "Leads", render: renderLeads },
  { path: "review", label: "Review queue", render: renderReview, badge: true },
  { path: "outreach", label: "Outreach", render: renderOutreach },
  { path: "icp", label: "ICP settings", render: renderIcp },
  { path: "reports", label: "Reports", render: renderReports },
];
let pollTimer = null;
export const ctx = { stopPolling: () => { clearInterval(pollTimer); pollTimer = null; }, poll: (fn, ms) => { ctx.stopPolling(); pollTimer = setInterval(fn, ms); } };

setUnauthorizedHandler(() => { session.token = null; session.user = null; toast("Session expired. Please sign in again.", "error"); renderLogin(); });

const logo = () => svg("svg", { viewBox: "0 0 32 32", width: 30, height: 30, "aria-hidden": "true" },
  svg("rect", { width: 32, height: 32, rx: 7, fill: "#1b2b38" }),
  svg("path", { d: "M16 6c2 4 6 6 6 11a6 6 0 0 1-12 0c0-2 1-3 2-4 0 2 1 3 2 3 0-4-1-6 2-10z", fill: "#f0a92e" }));

function renderLogin() {
  ctx.stopPolling();
  const err = h("div", { class: "err", role: "alert" });
  const email = h("input", { type: "email", name: "email", autocomplete: "username", required: true });
  const pw = h("input", { type: "password", name: "password", autocomplete: "current-password", required: true });
  const btn = h("button", { class: "primary", type: "submit" }, "Sign in");
  const form = h("form", { onsubmit: async (e) => {
    e.preventDefault(); btn.disabled = true; err.textContent = "";
    try {
      const r = await api("/auth/login", { method: "POST", body: { email: email.value, password: pw.value } });
      session.token = r.access_token; session.user = r.user; start();
    } catch (ex) { err.textContent = ex.message; } finally { btn.disabled = false; }
  } },
    h("div", { class: "field" }, h("label", { for: "le" }, "Email"), Object.assign(email, { id: "le" })),
    h("div", { class: "field" }, h("label", { for: "lp" }, "Password"), Object.assign(pw, { id: "lp" })), err, btn);
  clear(root).append(h("div", { class: "login" }, h("div", { class: "card" },
    h("div", { class: "brand", style: null }, logo(), h("div", {}, "Pilot Light", h("small", {}, "Sales lead qualification"))),
    h("p", { class: "muted small" }, "Sign in with the account your administrator created."), form)));
}

async function start() {
  if (!session.token) return renderLogin();
  try { session.user = session.user || (await api("/auth/me")); } catch { return renderLogin(); }
  const main = h("main", { class: "main", id: "main", tabindex: "-1" });
  const nav = h("nav", { class: "nav", "aria-label": "Main" });
  const shell = h("div", { class: "shell" },
    h("aside", { class: "side" }, h("div", { class: "brand" }, logo(), h("div", {}, "Pilot Light", h("small", {}, "Lead qualification"))), nav,
      h("div", { class: "who" }, h("b", {}, session.user.full_name), h("span", { class: "muted" }, session.user.role),
        h("div", {}, h("button", { class: "sm", onclick: async () => { try { await api("/auth/logout", { method: "POST" }); } catch { /* ignore */ } session.token = null; session.user = null; renderLogin(); } }, "Sign out")))),
    main);
  clear(root).append(shell);

  const route = async () => {
    ctx.stopPolling();
    const [path, ...rest] = (location.hash.replace(/^#\/?/, "") || "overview").split("/");
    const def = ROUTES.find((r) => r.path === path);
    clear(nav).append(...ROUTES.map((r) => h("a", { href: `#/${r.path}`, "aria-current": (r.path === path || (path === "lead" && r.path === "leads")) ? "page" : null },
      r.label, r.badge ? h("span", { class: "count", id: "navcount", hidden: true }) : null)));
    refreshBadge();
    clear(main);
    try {
      if (path === "lead" && rest[0]) await renderLeadDetail(main, rest[0], ctx);
      else await (def || ROUTES[0]).render(main, ctx);
    } catch (ex) { main.append(h("div", { class: "banner bad", role: "alert" }, ex.message)); }
    main.focus({ preventScroll: true });
  };
  window.onhashchange = route;
  route();
}

async function refreshBadge() {
  try {
    const list = await api("/approvals?status=pending");
    const el = document.getElementById("navcount");
    if (el) { el.textContent = list.length; el.hidden = list.length === 0; }
  } catch { /* badge is best-effort */ }
}

start();
