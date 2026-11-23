// 在已提交的工作区上检查页面资源、正常登录后主界面，以及无脚本时的失败关闭。
// 字段里只放公开标记 NOSSECRET-MARKER，不使用口令。
import { spawn, execSync } from "node:child_process";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";

const marker = "NOSSECRET-MARKER";
const username = "markeruser";
const tree = process.env.ZHIXU_TREE || "/workspace";
const sha = execSync("git rev-parse HEAD", { cwd: tree }).toString().trim();
const pageBase = execSync("git rev-parse b7cbfa0f3a5fbf556d5369e70109fac509a75ecd:web/index.html", { cwd: tree }).toString().trim();
const pageHead = execSync("git rev-parse HEAD:web/index.html", { cwd: tree }).toString().trim();
const root = await mkdtemp(path.join(tmpdir(), "page-recheck-"));
const dataDir = path.join(root, "data");
const accessLog = path.join(root, "access.log");
const outPath = process.env.OUT || path.join(tree, "docs/delivery/scans/page-recheck-6265ee4.json");

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

const appPort = await freePort();
const logConfigPath = path.join(root, "log.json");
await writeFile(logConfigPath, JSON.stringify({
  version: 1,
  disable_existing_loggers: false,
  formatters: { plain: { format: "%(message)s" } },
  handlers: { file: { class: "logging.FileHandler", formatter: "plain", filename: accessLog } },
  loggers: {
    "uvicorn.access": { handlers: ["file"], level: "INFO", propagate: false },
    "uvicorn.error": { handlers: ["file"], level: "INFO", propagate: false },
  },
}));
const server = spawn(
  "python3",
  ["-m", "uvicorn", "zhixu_server.main:create_app", "--factory", "--host", "127.0.0.1", "--port", String(appPort), "--log-config", logConfigPath],
  {
    cwd: `${tree}/server`,
    env: {
      ...process.env,
      PYTHONPATH: `/tmp/zhixu-dev-site:${tree}/server`,
      ZHIXU_DATA_DIR: dataDir,
      ZHIXU_HOST: "127.0.0.1",
      ZHIXU_PORT: String(appPort),
      ZHIXU_UPSTREAM_MODE: "unconfigured",
      ZHIXU_MODEL_BASE_URL: "",
      ZHIXU_MODEL_NAME: "",
      ZHIXU_MODEL_API_KEY: "",
      ZHIXU_ALLOWED_ORIGINS: `http://127.0.0.1:${appPort}`,
    },
    stdio: "ignore",
  },
);

async function waitHealth() {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${appPort}/api/health`);
      if (response.status === 200) return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
  }
  throw new Error("server did not start");
}

function cdp(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let next = 0;
  const pending = new Map();
  const listeners = [];
  const opened = new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve);
    ws.addEventListener("error", () => reject(new Error("cdp socket failed")));
  });
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const item = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) item.reject(new Error(message.error.message || "cdp error"));
      else item.resolve(message.result || {});
    } else if (message.method) {
      for (const listener of listeners) listener(message.method, message.params || {});
    }
  });
  return {
    ready: opened,
    on(listener) { listeners.push(listener); },
    send(method, params = {}) {
      const id = ++next;
      ws.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
    },
    close() { ws.close(); },
  };
}

function noteRequest(bucket, params) {
  const request = params.request || {};
  const url = String(request.url || "");
  let pathOnly = url;
  let query = "";
  try {
    const parsed = new URL(url);
    pathOnly = parsed.pathname;
    query = parsed.search;
  } catch { /* 保留原路径 */ }
  const post = String(request.postData || "");
  bucket.push({
    method: request.method || "",
    path: pathOnly,
    queryHadMarker: query.includes(marker),
    bodyHadMarker: post.includes(marker),
    resourceType: params.type || "",
  });
}

async function attributes(session, selector) {
  let doc;
  try {
    doc = await session.send("DOM.getDocument", { depth: 1 });
  } catch (error) {
    throw new Error(`getDocument ${selector}: ${error.message || error}`);
  }
  let found;
  try {
    found = await session.send("DOM.querySelector", { nodeId: doc.root.nodeId, selector });
  } catch (error) {
    throw new Error(`query ${selector} root=${doc.root?.nodeId}: ${error.message || error}`);
  }
  if (!found.nodeId) return { found: false, nodeId: 0, map: {} };
  let result;
  try {
    result = await session.send("DOM.getAttributes", { nodeId: found.nodeId });
  } catch (error) {
    throw new Error(`attrs ${selector} node=${found.nodeId}: ${error.message || error}`);
  }
  const list = result.attributes || [];
  const map = {};
  for (let i = 0; i < list.length; i += 2) map[list[i]] = list[i + 1];
  return { found: true, nodeId: found.nodeId, disabled: Object.hasOwn(map, "disabled"), map };
}

async function evaluate(session, expression) {
  const evaluated = await session.send("Runtime.evaluate", { expression, returnByValue: true });
  if (evaluated.exceptionDetails) {
    const text = evaluated.exceptionDetails.text || evaluated.result?.description || "evaluate failed";
    throw new Error(text);
  }
  return evaluated.result?.value;
}

async function center(session, selector) {
  const point = await evaluate(session, `(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2, disabled: Boolean(el.disabled) }; })()`);
  if (!point) throw new Error(`missing ${selector}`);
  return point;
}

async function clickSelector(session, selector) {
  const point = await center(session, selector);
  await session.send("Input.dispatchMouseEvent", { type: "mousePressed", x: point.x, y: point.y, button: "left", clickCount: 1 });
  await session.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: point.x, y: point.y, button: "left", clickCount: 1 });
  return point;
}

async function pressEnter(session) {
  const common = { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };
  await session.send("Input.dispatchKeyEvent", { type: "keyDown", ...common });
  await session.send("Input.dispatchKeyEvent", { type: "keyUp", ...common });
}

async function launchChrome(extraArgs) {
  const debugPort = await freePort();
  const profile = await mkdtemp(path.join(root, "chrome-"));
  const chrome = spawn("google-chrome", [
    "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--no-first-run",
    `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, ...extraArgs, "about:blank",
  ], { stdio: "ignore" });
  const deadline = Date.now() + 15000;
  let version;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${debugPort}/json/version`);
      if (response.ok) { version = await response.json(); break; }
    } catch { await new Promise((resolve) => setTimeout(resolve, 150)); }
  }
  if (!version) throw new Error("chrome devtools did not start");
  return { chrome, debugPort, version };
}

async function openPage(debugPort, { blockScripts }) {
  const tabResponse = await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, { method: "PUT" });
  const tab = await tabResponse.json();
  const session = cdp(tab.webSocketDebuggerUrl);
  await session.ready;
  const requests = [];
  const resources = [];
  session.on((method, params) => {
    if (method === "Network.requestWillBeSent") noteRequest(requests, params);
    if (method === "Network.responseReceived") {
      const url = String(params.response?.url || "");
      try {
        const parsed = new URL(url);
        if (parsed.pathname.endsWith(".js") || parsed.pathname.endsWith(".css") || parsed.pathname === "/") {
          resources.push({ path: parsed.pathname, status: params.response?.status || 0, mime: params.response?.mimeType || "" });
        }
      } catch { /* 忽略无法解析的地址 */ }
    }
    if (method === "Fetch.requestPaused") {
      const url = String(params.request?.url || "");
      const block = blockScripts && url.includes(".js");
      const command = block
        ? session.send("Fetch.failRequest", { requestId: params.requestId, errorReason: "BlockedByClient" })
        : session.send("Fetch.continueRequest", { requestId: params.requestId });
      command.catch(() => {});
    }
  });
  await session.send("Network.enable");
  await session.send("Page.enable");
  await session.send("DOM.enable");
  await session.send("Runtime.enable");
  if (blockScripts) await session.send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
  let navigated = false;
  const loaded = new Promise((resolve) => {
    const timer = setTimeout(resolve, 3000);
    session.on((method, params) => {
      if (!navigated) return;
      if (method === "Page.frameNavigated" && params.frame?.url?.includes("127.0.0.1")) {
        clearTimeout(timer);
        setTimeout(resolve, blockScripts ? 700 : 900);
      }
    });
  });
  navigated = true;
  await session.send("Page.navigate", { url: `http://127.0.0.1:${appPort}/` });
  await loaded;
  return { session, requests, resources, tab };
}

async function typeMarker(session) {
  await clickSelector(session, "#username");
  await session.send("Input.insertText", { text: username });
  await clickSelector(session, "#password");
  await session.send("Input.insertText", { text: marker });
  const typed = await evaluate(session, `(() => ({ user: document.querySelector('#username').value, pass: document.querySelector('#password').value }))()`);
  return { usernameTyped: typed.user === username, markerTyped: typed.pass === marker };
}

async function readState(session, requests, resources) {
  let view = null;
  let evalError = null;
  try {
    view = await evaluate(session, `(() => { const app = document.getElementById('app'); const form = document.getElementById('auth-form'); const login = document.getElementById('login'); return { appHidden: app ? app.classList.contains('hidden') : null, appClass: app ? app.className : null, loginDisabled: login ? login.disabled : null, formMethod: form ? form.getAttribute('method') : null, formAction: form ? form.getAttribute('action') : null }; })()`);
  } catch (error) {
    evalError = String(error.message || error);
  }
  const history = await session.send("Page.getNavigationHistory");
  const current = history.entries?.[history.currentIndex]?.url || "";
  let finalPath = current;
  let finalQueryHadMarker = false;
  try {
    const parsed = new URL(current);
    finalPath = parsed.pathname;
    finalQueryHadMarker = parsed.search.includes(marker);
  } catch { finalQueryHadMarker = current.includes(marker); }
  return {
    loginDisabled: view ? view.loginDisabled : null,
    formMethod: view ? view.formMethod : null,
    formAction: view ? view.formAction : null,
    appHidden: view ? view.appHidden : null,
    appClass: view ? view.appClass : null,
    evalError,
    finalPath,
    finalQueryHadMarker,
    requests: requests.filter((item) => item.path.startsWith("/") && !item.path.includes("devtools")),
    resources,
  };
}

async function act(session, action) {
  if (action === "click") {
    const point = await clickSelector(session, "form#auth-form button.primary");
    return { did: true, how: "Input.dispatchMouseEvent", disabledAtClick: point.disabled };
  }
  if (action === "enter") {
    await clickSelector(session, "#password");
    await pressEnter(session);
    return { did: true, how: "Input.dispatchKeyEvent Enter" };
  }
  if (action === "requestSubmit" || action === "formSubmit") {
    const expression = action === "requestSubmit"
      ? "(() => { try { document.getElementById('auth-form').requestSubmit(); return 'called'; } catch (error) { return 'threw:' + error.name; } })()"
      : "(() => { try { document.getElementById('auth-form').submit(); return 'called'; } catch (error) { return 'threw:' + error.name; } })()";
    try {
      const evaluated = await session.send("Runtime.evaluate", { expression, returnByValue: true });
      return { did: true, result: evaluated.result?.value ?? null, exception: Boolean(evaluated.exceptionDetails) };
    } catch (error) {
      return { did: false, reason: String(error.message || error) };
    }
  }
  return { did: false, reason: "unknown action" };
}

const report = {
  sha,
  pageIndexMatchesB7cbfa0: pageBase === pageHead,
  pageBlobB7cbfa0: pageBase,
  pageBlobHead: pageHead,
  marker,
  http: [],
  chrome: null,
  scenarios: [],
  markerInAccessLog: null,
  error: null,
};

try {
  await waitHealth();
  for (const asset of ["/markdown.js", "/templates.js", "/upload_rules.js", "/app.js", "/input_rules.js", "/stream_state.js"]) {
    const response = await fetch(`http://127.0.0.1:${appPort}${asset}`);
    report.http.push({ path: asset, status: response.status, contentType: response.headers.get("content-type") });
  }
  const modes = [
    { name: "normal", blockScripts: false, disableJs: false, actions: ["click"] },
    { name: "blocked-js", blockScripts: true, disableJs: false, actions: ["click", "enter", "requestSubmit", "formSubmit"] },
    { name: "disabled-js", blockScripts: false, disableJs: true, actions: ["click", "enter", "requestSubmit", "formSubmit"] },
  ];
  for (const mode of modes) {
    const launched = await launchChrome(mode.disableJs ? ["--blink-settings=scriptEnabled=false"] : []);
    if (!report.chrome) report.chrome = { browser: launched.version.Browser, protocol: launched.version["Protocol-Version"], userAgent: launched.version["User-Agent"] };
    try {
      for (const action of mode.actions) {
        let page;
        try {
          page = await openPage(launched.debugPort, { blockScripts: mode.blockScripts });
          const before = page.requests.length;
          const typed = await typeMarker(page.session);
          const actionResult = await act(page.session, action);
          actionResult.typed = typed;
          if (mode.name === "normal") {
            await new Promise((resolve) => setTimeout(resolve, 500));
            const register = await center(page.session, "#register");
            if (register.disabled === false) await clickSelector(page.session, "#register");
          }
          await new Promise((resolve) => setTimeout(resolve, 700));
          const state = await readState(page.session, page.requests.slice(before), page.resources);
          report.scenarios.push({ mode: mode.name, action, actionResult, ...state, markerInUrl: state.finalQueryHadMarker || state.requests.some((item) => item.queryHadMarker) });
        } catch (error) {
          report.scenarios.push({ mode: mode.name, action, error: String(error.message || error), tested: false });
        } finally {
          if (page) page.session.close();
        }
      }
    } finally {
      launched.chrome.kill();
    }
  }
  const access = await readFile(accessLog, "utf8").catch(() => "");
  report.markerInAccessLog = access.includes(marker);
  const redacted = access.split(marker).join("[MARKER]").split(username).join("[USER]");
  await writeFile(path.join(path.dirname(outPath), "page-recheck-6265ee4-access.log"), redacted);
} catch (error) {
  report.error = String(error.message || error);
} finally {
  server.kill();
  await writeFile(outPath, JSON.stringify(report, null, 2));
  console.log(outPath);
  console.log(JSON.stringify({ sha: report.sha, error: report.error, http: report.http, markerInAccessLog: report.markerInAccessLog, scenarios: report.scenarios.map((item) => ({ mode: item.mode, action: item.action, did: item.actionResult?.did, result: item.actionResult?.result, appHidden: item.appHidden, markerInUrl: item.markerInUrl, loginDisabled: item.loginDisabled })) }));
}
