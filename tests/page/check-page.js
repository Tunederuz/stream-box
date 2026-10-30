// Companion app check: remote.html loaded in jsdom against a fake API (tools/qmlshots/fixtures.json, plus the
// page-only endpoints of fixtures.json here), on each tab with every Settings group open, then again without the system
// part (Inlet app: /api/features {system: false}). Fails on a script error (thrown, rejected, console.error), a
// "status error" message shown by the page, or, without the system part, a system route read or its blocks shown.
//   node check-page.js <repo>          (tools/check.sh page, .github/workflows/checks.yml)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const repo = path.resolve(process.argv[2] || "../..");
const html = fs.readFileSync(path.join(repo, "web", "remote.html"), "utf8");
const api = Object.assign({}, JSON.parse(fs.readFileSync(path.join(repo, "tools/qmlshots/fixtures.json"), "utf8")),
                          JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures.json"), "utf8")));
const problems = [];
// The system part's routes (absent from the Inlet app: 404)
const SYSTEM_ROUTES = ["/api/health", "/api/wifi", "/api/audio", "/api/local_update", "/api/branches", "/api/backup",
                       "/api/bluetooth", "/api/dev", "/api/ssh", "/api/install", "/api/display", "/api/update_prompt"];
process.on("unhandledRejection", (e) => problems.push("unhandled rejection: " + (e && e.stack || e)));

function load(tab, system = true) {
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => problems.push(`[${tab}] ${e.message}${e.detail ? ": " + (e.detail.stack || e.detail) : ""}`));
  vc.on("error", (...a) => problems.push(`[${tab}] console.error: ${a.map((x) => x && x.stack || x).join(" ")}`));
  return new JSDOM(html, {
    url: "http://box.local:8080/", runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.localStorage.setItem("tab", tab);
      w.localStorage.setItem("lang", "fr");
      w.localStorage.setItem("groups", JSON.stringify(["channels", "accounts", "playback", "picture", "look", "network", "updates", "backup"]));
      w.fetch = async (url, opts = {}) => {
        const u = new URL(url, "http://box.local:8080/");
        let body = {};
        if (u.pathname === "/api/features") body = { system };
        else if (!system && SYSTEM_ROUTES.includes(u.pathname)) {
          problems.push(`[${tab}, no system] system route read: ${u.pathname}`);
          return { ok: false, status: 404, json: async () => ({ error: "not found" }), text: async () => "" };
        }
        else if (u.pathname.startsWith("/locales/")) body = JSON.parse(fs.readFileSync(path.join(repo, u.pathname), "utf8"));
        else if ((opts.method || "GET") !== "GET") body = { ok: true };
        else if (u.pathname in api) body = api[u.pathname];
        else problems.push(`[${tab}] no fixture for GET ${u.pathname}`);
        return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(body)), text: async () => JSON.stringify(body) };
      };
      w.HTMLElement.prototype.scrollIntoView = () => {};
      w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {} });
    },
  });
}

(async () => {
  const doms = ["remote", "settings"].map((t) => load(t));
  const players = ["remote", "settings"].map((t) => load(t, false));   // without the system part
  await new Promise((r) => setTimeout(r, 3000));   // first loads and renders (fetches are immediate)
  for (const [i, dom] of players.entries()) {
    const d = dom.window.document;
    if (!d.documentElement.classList.contains("no-system")) problems.push(`[${i ? "settings" : "remote"}, no system] .no-system not set`);
    if (!d.querySelectorAll("[data-system]").length) problems.push("no [data-system] block: the page hides nothing");
    dom.window.close();
  }
  for (const [i, dom] of doms.entries()) {
    for (const s of dom.window.document.querySelectorAll(".status.error, .status.bad"))
      if (s.textContent.trim() && !s.closest("[hidden]")) problems.push(`[${["remote", "settings"][i]}] error shown: ${s.id || s.className}: ${s.textContent.trim()}`);
    dom.window.close();
  }
  if (problems.length) {
    console.log(problems.join("\n"));
    process.exit(1);
  }
  console.log("page: remote.html loads on both tabs, no script error; without the system part, its blocks hidden, its routes not read");
  process.exit(0);
})();
