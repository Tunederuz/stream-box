// Companion app check: remote.html loaded in jsdom against a fake API (tools/qmlshots/fixtures.json, plus the
// page-only endpoints of fixtures.json here), on each tab with every Settings group open. Fails on a script error
// (thrown, rejected, console.error) or a "status error" message shown by the page.
//   node check-page.js <repo>          (tools/check.sh page, .github/workflows/checks.yml)
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const repo = path.resolve(process.argv[2] || "../..");
const html = fs.readFileSync(path.join(repo, "remote.html"), "utf8");
const api = Object.assign({}, JSON.parse(fs.readFileSync(path.join(repo, "tools/qmlshots/fixtures.json"), "utf8")),
                          JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures.json"), "utf8")));
const problems = [];
process.on("unhandledRejection", (e) => problems.push("unhandled rejection: " + (e && e.stack || e)));

function load(tab) {
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
        if (u.pathname.startsWith("/locales/")) body = JSON.parse(fs.readFileSync(path.join(repo, u.pathname), "utf8"));
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
  const doms = ["remote", "settings"].map(load);
  await new Promise((r) => setTimeout(r, 3000));   // first loads and renders (fetches are immediate)
  for (const [i, dom] of doms.entries()) {
    for (const s of dom.window.document.querySelectorAll(".status.error, .status.bad"))
      if (s.textContent.trim() && !s.closest("[hidden]")) problems.push(`[${["remote", "settings"][i]}] error shown: ${s.id || s.className}: ${s.textContent.trim()}`);
    dom.window.close();
  }
  if (problems.length) {
    console.log(problems.join("\n"));
    process.exit(1);
  }
  console.log("page: remote.html loads on both tabs, no script error");
  process.exit(0);
})();
