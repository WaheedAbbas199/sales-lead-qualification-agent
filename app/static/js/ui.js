// DOM helpers. We NEVER use innerHTML: every value is inserted as a text node, so lead data cannot inject markup.
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "value") el.value = v;
    else if (k === "checked" || k === "disabled" || k === "selected" || k === "required" || k === "open") el[k] = !!v;
    else if (k === "cssVars") Object.entries(v).forEach(([n, val]) => el.style.setProperty(n, val));
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, children);
  return el;
}
function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}
const SVG = "http://www.w3.org/2000/svg";
export function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  append(el, children);
  return el;
}
export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

export function toast(msg, kind = "info") {
  const t = h("div", { class: `toast ${kind === "error" ? "error" : ""}` }, msg);
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), kind === "error" ? 8000 : 4000);
}

export const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—");
export const fmtDay = (iso) => (iso ? new Date(iso + (iso.length === 10 ? "T00:00" : "")).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—");
export const pretty = (s) => (s ? String(s).replace(/_/g, " ") : "—");
export const money = (v) => (v === null || v === undefined || v === "" ? "—" : `$${Number(v).toLocaleString()}`);

export const chip = (value, extra = "") => h("span", { class: `chip ${value || "unknown"} ${extra}` }, pretty(value || "unknown"));
export const prov = (p) => h("span", { class: `prov ${p}` }, pretty(p));
export const bar = (pct, amber = false) => h("div", { class: `bar ${amber ? "amber" : ""}`, role: "img", "aria-label": `${Math.round(pct)}%` },
  h("i", { cssVars: { "--w": `${Math.max(0, Math.min(100, pct))}%` } }));

export function safeUrl(u) {
  try { const x = new URL(u); return x.protocol === "https:" || x.protocol === "http:" ? x.href : null; } catch { return null; }
}

export function gauge(score, priority) {
  const r = 48, c = 2 * Math.PI * r, pct = Math.max(0, Math.min(100, score ?? 0));
  const cls = priority === "high" ? "high" : priority === "low" ? "low" : "";
  return svg("svg", { class: `gauge ${cls}`, viewBox: "0 0 120 120", width: 120, height: 120, role: "img", "aria-label": `Score ${score ?? "not scored"} of 100` },
    svg("circle", { class: "track", cx: 60, cy: 60, r, fill: "none", "stroke-width": 10 }),
    svg("circle", { class: "arc", cx: 60, cy: 60, r, fill: "none", "stroke-width": 10, "stroke-linecap": "round",
      "stroke-dasharray": c, "stroke-dashoffset": c * (1 - pct / 100), transform: "rotate(-90 60 60)" }),
    svg("text", { x: 60, y: 62, "text-anchor": "middle", "font-size": 28, fill: "currentColor" }, score == null ? "—" : Math.round(score)),
    svg("text", { x: 60, y: 82, "text-anchor": "middle", "font-size": 10, fill: "currentColor", opacity: 0.6 }, "OUT OF 100"));
}

// ---------- forms & dialogs ----------
export function field(label, input, { hint, id } = {}) {
  const fid = id || `f_${Math.random().toString(36).slice(2, 8)}`;
  input.id = fid;
  const err = h("div", { class: "err", id: `${fid}_err`, "aria-live": "polite" });
  input.setAttribute("aria-describedby", err.id);
  return h("div", { class: "field" }, h("label", { for: fid }, label, hint ? h("span", { class: "hint" }, ` ${hint}`) : null), input, err);
}
export const setFieldErrors = (root, details) => {
  root.querySelectorAll(".err").forEach((e) => (e.textContent = ""));
  (Array.isArray(details) ? details : []).forEach((d) => {
    const input = root.querySelector(`[name="${d.field}"]`);
    const err = input && root.querySelector(`#${input.id}_err`);
    if (err) err.textContent = d.message;
  });
};

export function modal({ title, body, actions = [], onClose }) {
  const dlg = h("dialog", { "aria-labelledby": "dlg_title" });
  const close = () => { dlg.close(); dlg.remove(); onClose?.(); };
  dlg.append(
    h("div", { class: "dh" }, h("h2", { id: "dlg_title" }, title), h("button", { class: "ghost sm", onclick: close, "aria-label": "Close" }, "✕")),
    h("div", { class: "db" }, body),
    actions.length ? h("div", { class: "df" }, actions.map((a) => h("button", { class: a.class || "", onclick: () => a.onClick(close, dlg) }, a.label))) : null,
  );
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  document.body.append(dlg);
  dlg.showModal();
  return { close, dlg };
}

export const confirmDialog = (title, message, label = "Confirm", danger = false) => new Promise((resolve) => {
  modal({ title, body: h("p", {}, message), onClose: () => resolve(false),
    actions: [{ label: "Cancel", onClick: (c) => { c(); } }, { label, class: danger ? "danger" : "primary", onClick: (c) => { resolve(true); c(); } }] });
});

export function download(filename, text, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = h("a", { href: url, download: filename });
  document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}

export function table(columns, rows, { empty = "Nothing here yet." } = {}) {
  if (!rows.length) return h("div", { class: "tablewrap" }, h("div", { class: "empty" }, empty));
  return h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, columns.map((c) => h("th", { scope: "col" }, c.header))))
    , h("tbody", {}, rows.map((r) => h("tr", {}, columns.map((c) => h("td", {}, c.render(r))))))));
}
