import { copyFeedback } from "./copy_feedback.js";
import { normalizeContent, shouldSendOnEnter } from "./input_rules.js";
import { renderMarkdown } from "./markdown.js";
import { applyEvent, createState, visibleCitations } from "./stream_state.js";
import { templateState } from "./templates.js";
import { fileStatusLabel, uploadBlockReason } from "./upload_rules.js";

const $ = (id) => document.getElementById(id);
const state = createState();
const readers = new Map();
let activeId = null;
let busyRequest = null;
let currentFiles = [];

function toast(text) {
  $("toast").textContent = text;
  $("toast").classList.add("show");
  setTimeout(() => $("toast").classList.remove("show"), 2800);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const csrf = document.cookie.split("; ").find((item) => item.startsWith("zhixu_csrf="));
  if (csrf && options.method && options.method !== "GET") {
    headers.set("X-CSRF-Token", decodeURIComponent(csrf.split("=")[1]));
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  return response;
}

function showApp(on) {
  $("auth-view").classList.toggle("hidden", on);
  $("app").classList.toggle("hidden", !on);
}

async function boot() {
  const me = await api("/api/auth/me");
  if (!me.ok) return;
  showApp(true);
  const health = await api("/api/health");
  if (health.ok) {
    const body = await health.json();
    $("mode-label").textContent = body.upstream_mode === "live" ? "真实模型模式" : body.upstream_mode === "fixture" ? "夹具模式，不是真实联调" : "模型未配置";
  }
  await refreshHistory();
}

$("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await authenticate("/api/auth/login");
});
$("register").addEventListener("click", () => authenticate("/api/auth/register"));

async function authenticate(path) {
  const response = await api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: $("username").value.trim(), password: $("password").value }),
  });
  if (!response.ok) {
    const body = await response.json();
    $("auth-message").textContent = body.error?.message || "登录失败";
    return;
  }
  $("auth-message").textContent = "";
  showApp(true);
  await boot();
}

$("logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  activeId = null;
  showApp(false);
});

$("new-chat").addEventListener("click", async () => {
  const response = await api("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!response.ok) return toast("没有创建会话");
  const body = await response.json();
  await openConversation(body.id);
  await refreshHistory();
});

$("history-search").addEventListener("input", refreshHistory);

async function refreshHistory() {
  const q = $("history-search").value.trim();
  const response = await api("/api/conversations?limit=30" + (q ? "&q=" + encodeURIComponent(q) : ""));
  if (!response.ok) return;
  const body = await response.json();
  const root = $("history");
  root.replaceChildren();
  body.items.forEach((item) => {
    const button = document.createElement("button");
    button.className = "history-title";
    button.textContent = item.title + " · " + (item.updated_at || "").slice(5, 16).replace("T", " ");
    button.onclick = () => openConversation(item.id);
    root.append(button);
  });
}

async function openConversation(id) {
  activeId = id;
  state.activeId = id;
  const response = await api("/api/conversations/" + id);
  if (!response.ok) return toast("不能打开这个会话");
  const body = await response.json();
  $("page-title").textContent = body.title;
  $("welcome").classList.toggle("hidden", body.messages.length > 0);
  $("chat").classList.toggle("hidden", body.messages.length === 0);
  renderMessages(body.messages);
  renderFiles(body.files || []);
  renderTemplates(body.files || []);
  const running = body.messages.find((item) => ["accepted", "streaming", "verifying"].includes(item.status));
  if (running && running.request_id) subscribe(id, running.request_id, "0");
}

function renderMessages(messages) {
  const root = $("messages");
  root.replaceChildren();
  messages.forEach((message) => {
    const row = document.createElement("div");
    row.className = "message " + message.role;
    if (message.role === "user") {
      const bubble = document.createElement("div");
      bubble.className = "user-bubble";
      bubble.textContent = message.content;
      row.append(bubble);
    } else {
      const text = document.createElement("div");
      text.className = "answer-text";
      renderMarkdown(text, message.content || "");
      if (message.status === "streaming" || message.status === "accepted") text.classList.add("provisional");
      row.append(text);
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = labelFor(message.status);
      if (message.status === "failed" || message.status === "withdrawn") badge.classList.add("bad");
      if (message.status === "streaming" || message.status === "stopped") badge.classList.add("warn");
      row.append(badge);
      (message.citations || []).forEach((cite) => {
        const button = document.createElement("button");
        button.className = "citation";
        button.type = "button";
        button.textContent = "来源 · " + (cite.page ? "第 " + cite.page + " 页 " : "") + "第 " + (cite.paragraph || "?") + " 段";
        button.onclick = () => openPreview(cite);
        row.append(button);
      });
      if (message.status === "failed") {
        const retry = document.createElement("button");
        retry.type = "button";
        retry.textContent = "重试";
        retry.onclick = () => send(message.user_message_id);
        row.append(retry);
      }
      const copy = document.createElement("button");
      copy.type = "button";
      copy.textContent = "复制回答";
      copy.onclick = async () => {
        try {
          await navigator.clipboard.writeText(message.content || "");
          toast(copyFeedback(true));
        } catch {
          toast(copyFeedback(false));
        }
      };
      row.append(copy);
      if (message.status === "completed" || message.status === "withdrawn" || message.status === "stopped") {
        const feedback = document.createElement("button");
        feedback.type = "button";
        feedback.textContent = "反馈";
        feedback.onclick = () => sendFeedback(message.id);
        row.append(feedback);
      }
    }
    root.append(row);
  });
}

function labelFor(status) {
  return {
    accepted: "等待生成",
    streaming: "生成中 · 未核验",
    verifying: "正在核对出处",
    completed: "已完成",
    withdrawn: "未采用无依据结论",
    stopped: "已停止",
    failed: "失败",
  }[status] || status;
}

function renderFiles(files) {
  currentFiles = files;
  const root = $("attachments");
  root.replaceChildren();
  files.forEach((file) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "file-chip";
    const reason = file.error_message ? " · " + file.error_message : "";
    const notice = file.parse_notice ? " · " + file.parse_notice : "";
    chip.textContent = file.name + " · " + fileStatusLabel(file.status) + reason + notice;
    chip.onclick = () => openPreview({ file_id: file.file_id, version: file.version, page: file.page });
    root.append(chip);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "删除";
    remove.onclick = () => deleteFile(file.file_id);
    root.append(remove);
  });
}

function renderTemplates(files) {
  const root = $("templates");
  root.replaceChildren();
  const states = templateState(files);
  states.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.prompt = item.prompt;
    button.disabled = !item.enabled;
    button.textContent = item.label;
    button.title = item.reason;
    root.append(button);
  });
  const note = states.find((item) => item.reason);
  $("template-note").textContent = note
    ? note.reason + "。自由提问仍可用，发送前可以改字。"
    : "模板在发送前可以修改。文档类模板只在有就绪文档时可用。";
}

$("templates").addEventListener("click", (event) => {
  const button = event.target.closest("[data-prompt]");
  if (!button || button.disabled) return;
  $("prompt").value = button.dataset.prompt;
  $("prompt").focus();
});

$("prompt").addEventListener("keydown", (event) => {
  if (!shouldSendOnEnter(event)) return;
  event.preventDefault();
  send();
});

$("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  if (busyRequest) {
    stop();
    return;
  }
  send();
});

async function send(retryOf) {
  const content = normalizeContent($("prompt").value);
  if (!retryOf && !content) {
    toast("写下你的问题，再开始对话");
    return;
  }
  if (!activeId) {
    const created = await api("/api/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (!created.ok) return toast("请先新建会话");
    activeId = (await created.json()).id;
  }
  const payload = retryOf ? { content: content || "重试", retry_of_message_id: retryOf } : { content };
  const response = await api("/api/conversations/" + activeId + "/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (response.status === 409) return toast(body.error?.message || "正在生成");
  if (!response.ok) return toast(body.error?.message || "发送失败");
  if (!retryOf) $("prompt").value = "";
  busyRequest = { conversationId: activeId, requestId: body.request_id };
  $("send").textContent = "■";
  subscribe(activeId, body.request_id, "0");
}

function subscribe(conversationId, requestId, lastId) {
  if (readers.has(requestId)) return;
  const controller = new AbortController();
  readers.set(requestId, controller);
  readStream(conversationId, requestId, lastId, controller.signal);
}

async function readStream(conversationId, requestId, lastId, signal) {
  const response = await api("/api/requests/" + requestId + "/events?last_event_id=" + encodeURIComponent(lastId), { signal });
  if (!response.ok || !response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let latest = lastId;
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    parts.forEach((part) => {
      const lines = part.split("\n");
      let id = latest;
      let name = "message";
      let data = "";
      lines.forEach((line) => {
        if (line.startsWith("id:")) id = line.slice(3).trim();
        if (line.startsWith("event:")) name = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      });
      latest = id;
      const payload = data ? JSON.parse(data) : {};
      const request = applyEvent(state, conversationId, requestId, name, payload);
      if (conversationId === activeId) paintLive(request);
      if (name === "done" || name === "error") {
        busyRequest = null;
        $("send").textContent = "↑";
        if (conversationId === activeId) openConversation(conversationId);
      }
    });
  }
}

function paintLive(request) {
  if (!request || request.conversationId !== activeId && request.conversationId) return;
  $("welcome").classList.add("hidden");
  $("chat").classList.remove("hidden");
  const root = $("messages");
  let box = root.querySelector("[data-request='" + request.requestId + "']");
  if (!box) {
    box = document.createElement("div");
    box.className = "message assistant";
    box.dataset.request = request.requestId;
    root.append(box);
  }
  box.replaceChildren();
  const text = document.createElement("div");
  text.className = "answer-text" + (request.provisional ? " provisional" : "");
  text.textContent = request.text;
  const badge = document.createElement("span");
  badge.className = "badge warn";
  badge.textContent = request.provisional ? "未核验" : labelFor(request.status);
  box.append(text, badge);
  visibleCitations(request).forEach((cite) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "citation";
    button.textContent = "已核对出处 · 第 " + (cite.paragraph || "?") + " 段";
    button.onclick = () => openPreview(cite);
    box.append(button);
  });
}

async function stop() {
  if (!busyRequest) return;
  await api("/api/requests/" + busyRequest.requestId + "/cancel", { method: "POST" });
}

$("attach").onclick = () => $("files").click();
$("files").onchange = () => upload($("files").files);
$("composer").addEventListener("drop", (event) => {
  event.preventDefault();
  upload(event.dataTransfer.files);
});
$("composer").addEventListener("dragover", (event) => event.preventDefault());

async function upload(list) {
  if (!activeId) return toast("请先新建会话");
  for (const file of Array.from(list || [])) {
    const reason = uploadBlockReason(currentFiles, file);
    if (reason) {
      toast(file.name + "：" + reason);
      continue;
    }
    const form = new FormData();
    form.set("conversation_id", activeId);
    form.set("file", file);
    const response = await api("/api/files", { method: "POST", body: form });
    const body = await response.json();
    if (!response.ok) {
      toast(body.error?.message || "上传失败");
      continue;
    }
    if (body.reused) toast("这是已有文件，已再次关联，没有重复保存");
    await pollFile(body.file_id);
  }
  if (activeId) openConversation(activeId);
}

async function pollFile(fileId) {
  for (let i = 0; i < 60; i += 1) {
    const response = await api("/api/files/" + fileId + "/status");
    if (!response.ok) return;
    const body = await response.json();
    toast(fileNameStatus(body));
    if (body.status === "ready" || body.status === "failed") return;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
}

function fileNameStatus(body) {
  const progress = Number.isInteger(body.progress) ? " " + body.progress + "%" : "";
  return fileStatusLabel(body.status) + progress + (body.error_message ? "：" + body.error_message : "");
}

async function deleteFile(fileId) {
  if (!window.confirm("确认从在线数据中删除这个文件？删除后不能在这里恢复。")) return;
  const response = await api("/api/files/" + fileId + "?confirm=true", { method: "DELETE" });
  if (!response.ok && response.status !== 204) return toast("没有删除文件");
  toast("文件已从在线数据移除");
  if (activeId) openConversation(activeId);
}

async function sendFeedback(messageId) {
  const reason = window.prompt("反馈原因：incorrect、incomplete、citation、format、other", "citation");
  if (!reason) return;
  const note = window.prompt("可选短说明，不要填写密码或整段隐私", "") || "";
  const response = await api("/api/messages/" + messageId + "/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason, note }),
  });
  if (!response.ok) {
    const body = await response.json();
    toast(body.error?.message || "反馈没有保存");
    return;
  }
  toast("反馈已保存");
}

$("rename").onclick = async () => {
  if (!activeId) return toast("请先打开会话");
  const title = window.prompt("新的会话标题", $("page-title").textContent || "");
  if (!title) return;
  const response = await api("/api/conversations/" + activeId, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!response.ok) return toast("没有改成标题");
  const body = await response.json();
  $("page-title").textContent = body.title;
  refreshHistory();
};

$("delete-conversation").onclick = async () => {
  if (!activeId) return toast("请先打开会话");
  if (!window.confirm("确认删除这个会话？此操作会立刻从在线列表消失。")) return;
  const deleteFiles = window.confirm("是否同时删除只属于这个会话的附件？确定=删除附件，取消=只删除会话并停用附件。");
  const response = await api(
    "/api/conversations/" + activeId + "?confirm=true&delete_files=" + (deleteFiles ? "true" : "false"),
    { method: "DELETE" },
  );
  if (!response.ok && response.status !== 204) return toast("没有删除会话");
  activeId = null;
  toast(deleteFiles ? "会话和可删除的附件已从在线数据移除" : "会话已删除，附件按选择保留");
  refreshHistory();
};

$("delete-account").onclick = async () => {
  if (!window.confirm("确认删除当前账号的在线数据？会话、文件和登录状态会立即失效。")) return;
  const response = await api("/api/auth/me?confirm=true", { method: "DELETE" });
  if (!response.ok && response.status !== 204) return toast("没有删除账号");
  activeId = null;
  showApp(false);
  toast("账号在线数据已删除");
};

async function openPreview(cite) {
  const params = new URLSearchParams({ version: String(cite.version) });
  if (cite.paragraph) params.set("paragraph", String(cite.paragraph));
  if (cite.page) params.set("page", String(cite.page));
  if (cite.quote) params.set("quote", cite.quote);
  const response = await api("/api/files/" + cite.file_id + "/preview?" + params.toString());
  const body = await response.json();
  $("preview").classList.remove("hidden");
  if (!response.ok) {
    $("preview-title").textContent = "无法打开原文";
    $("preview-meta").textContent = body.error?.message || "请重新打开";
    $("preview-content").textContent = "";
    return;
  }
  $("preview-title").textContent = body.name;
  $("preview-meta").textContent = body.highlight_error || ("版本 " + body.version + " · 半开区间");
  const root = $("preview-content");
  root.replaceChildren();
  const highlight = body.highlights && body.highlights[0];
  if (highlight && highlight.exact_match && body.content.includes(highlight.quote)) {
    const at = body.content.indexOf(highlight.quote);
    root.append(document.createTextNode(body.content.slice(0, at)));
    const mark = document.createElement("mark");
    mark.textContent = highlight.quote;
    root.append(mark, document.createTextNode(body.content.slice(at + highlight.quote.length)));
  } else {
    root.textContent = body.content || "";
  }
}

$("preview-close").onclick = () => $("preview").classList.add("hidden");
$("menu").onclick = () => {
  $("sidebar").classList.add("open");
  $("scrim").classList.remove("hidden");
};
$("scrim").onclick = () => {
  $("sidebar").classList.remove("open");
  $("scrim").classList.add("hidden");
};

boot();
