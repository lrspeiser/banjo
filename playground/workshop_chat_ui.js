// Conversational UI layer for Workshop Mode.
//
// workshop.js remains the authoritative renderer/editor. This module upgrades
// its one-line component-chat form into a transcript and observes the existing
// Workshop API request/response so conversation UX can evolve independently of
// geometry rendering. The server-side workshop_chat agent still owns every
// bounded design tool and mutation.

const $ = (q) => document.querySelector(q);
const form = $("#ws-component-chat");
const oldInput = $("#ws-component-chat-text");
if (!form || !oldInput) throw new Error("Workshop chat form is unavailable");

const history = [];
let keyConfigured = false;
let pending = null;
let pendingBubble = null;
let pendingOriginal = "";

function el(tag, attrs = {}, text = "") {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  if (text) node.textContent = text;
  return node;
}

const heading = form.previousElementSibling;
if (heading && heading.tagName === "H3") heading.textContent = "Workshop assistant";
const intro = el("p", { class: "ws-chat-intro" },
  "Ask about the object or tell Workshop what to change. It can inspect components, 3D positions, interfaces, physics, tests, materials and My Library, then use several tools in one turn.");
const log = el("div", { id: "ws-chat-log", role: "log", "aria-live": "polite", "aria-label": "Workshop assistant conversation" });
const status = el("div", { id: "ws-chat-status", class: "ws-chat-status", "aria-live": "polite" });
form.parentElement.insertBefore(intro, form);
form.parentElement.insertBefore(log, form);
form.parentElement.insertBefore(status, form.nextSibling);

const textarea = el("textarea", {
  id: "ws-component-chat-text", rows: "3", maxlength: "4000",
  placeholder: "Try: make all four legs longer and thinner, then tell me what that does to stability",
  "aria-label": "Message Workshop assistant",
});
oldInput.replaceWith(textarea);
const send = form.querySelector("button[type=submit]");
if (send) send.textContent = "Send";

function appendMessage(role, text, options = {}) {
  const row = el("div", { class: `ws-chat-message ${role}${options.working ? " working" : ""}` });
  const who = el("span", { class: "ws-chat-who" }, role === "user" ? "You" : "Workshop");
  const body = el("div", { class: "ws-chat-body" }, text);
  row.append(who, body);
  if (options.tools && options.tools.length) {
    const details = el("details", { class: "ws-chat-tools" });
    details.append(el("summary", {}, `${options.tools.length} Workshop tool step${options.tools.length === 1 ? "" : "s"}`));
    const list = el("ul");
    for (const step of options.tools) {
      const item = el("li", { class: step.ok === false ? "bad" : "" }, `${step.tool}: ${step.summary || "done"}`);
      list.append(item);
    }
    details.append(list);
    row.append(details);
  }
  log.append(row);
  log.scrollTop = log.scrollHeight;
  return row;
}

function finishWorking() {
  if (pendingBubble) pendingBubble.remove();
  pendingBubble = null;
  pending = null;
  pendingOriginal = "";
  status.textContent = "";
  textarea.disabled = false;
  if (send) send.disabled = false;
}

function assistant(text, tools = []) {
  const clean = String(text || "").trim() || "Done.";
  appendMessage("assistant", clean, { tools });
  history.push({ role: "assistant", content: clean });
  if (history.length > 20) history.splice(0, history.length - 20);
}

appendMessage("assistant",
  "I can work on the whole design or a selected component. Tell me what you want changed, or ask me to inspect the geometry or physics first.");

// We only inject transcript context when an LLM key is configured. The
// deterministic local fallback remains clean and keyword-bounded for CI/dev.
fetch("/api/status").then((r) => r.json()).then((answer) => {
  keyConfigured = Boolean(answer.key_configured);
}).catch(() => { keyConfigured = false; });

function selectedComponentName() {
  const text = $("#ws-selected-part")?.textContent || "";
  if (!text || /^Click a part/i.test(text)) return null;
  return text.split(" · ")[0].trim() || null;
}

function firstComponentButton() {
  return $("#ws-parts .ws-part-link");
}

function deicticEditWithoutSelection(message) {
  if (selectedComponentName()) return false;
  const edit = /\b(longer|shorter|thicker|thinner|wider|narrower|material|iron|oak|aluminum|aluminium)\b/i.test(message);
  const deictic = /\b(this|that|it|selected|the part)\b/i.test(message);
  const semanticSet = /\b(legs?|wheels?|posts?|beams?|braces?|aprons?|stretchers?|axles?|handles?|tops?|surfaces?|panels?|shelves?)\b/i.test(message);
  return edit && deictic && !semanticSet;
}

function conversationContext(current) {
  if (!keyConfigured) return current;
  const prior = history.slice(0, -1).slice(-10);
  const lines = prior.map((row) => `${row.role === "user" ? "User" : "Workshop"}: ${row.content}`);
  const selection = selectedComponentName();
  const selectionLine = selection
    ? `The user currently has component ${selection} selected in the 3D Workshop.`
    : "No component is selected in the 3D Workshop. If the API transports a placeholder component, do not treat it as a user selection.";
  return [
    "WORKSHOP CONVERSATION CONTEXT (use this for references such as 'those' or 'a little more'):",
    ...lines,
    selectionLine,
    `CURRENT USER REQUEST: ${current}`,
  ].join("\n");
}

// Capture before workshop.js's form.onsubmit handler. If no component is
// selected, pick one only as a transport placeholder for the old endpoint; the
// injected LLM context explicitly says that it is not a real user selection.
form.addEventListener("submit", (event) => {
  const message = textarea.value.trim();
  if (!message) return;
  if (deicticEditWithoutSelection(message)) {
    event.preventDefault();
    event.stopImmediatePropagation();
    assistant("Which component do you mean? Click it in the 3D view, or name the group—for example, ‘all the legs’.");
    return;
  }
  const hadSelection = Boolean(selectedComponentName());
  if (!hadSelection) firstComponentButton()?.click();
  pendingOriginal = message;
  history.push({ role: "user", content: message });
  if (history.length > 20) history.splice(0, history.length - 20);
  appendMessage("user", message);
  pendingBubble = appendMessage("assistant", "Working… inspecting the design and choosing Workshop tools.", { working: true });
  status.textContent = "Working — the design stays unchanged until this turn completes.";
  textarea.disabled = true;
  if (send) send.disabled = true;
  pending = { hadSelection };
}, true);

// Observe the same HTTP call workshop.js already makes. This preserves the
// existing candidate/renderer state machine while giving the model recent
// conversation context and giving the user visible tool/result feedback.
const nativeFetch = window.fetch.bind(window);
window.fetch = async function workshopChatFetch(resource, init = {}) {
  let isChat = false;
  let requestBody = null;
  const url = typeof resource === "string" ? resource : String(resource?.url || resource);
  if (url.includes("/api/workshop/candidates") && init && typeof init.body === "string") {
    try {
      requestBody = JSON.parse(init.body);
      isChat = Boolean(requestBody && requestBody.component_chat);
      if (isChat && pendingOriginal) {
        requestBody.component_chat.message = conversationContext(pendingOriginal);
        init = { ...init, body: JSON.stringify(requestBody) };
        status.textContent = keyConfigured
          ? "Working — Workshop may inspect geometry, physics, library items and apply multiple edits."
          : "Working — applying deterministic Workshop tools.";
      }
    } catch { /* leave non-JSON or unrelated requests untouched */ }
  }
  try {
    const response = await nativeFetch(resource, init);
    if (isChat) {
      let answer = null;
      try { answer = await response.clone().json(); } catch { /* handled below */ }
      if (response.ok && answer && answer.workshop_chat) {
        const chat = answer.workshop_chat;
        finishWorking();
        assistant(chat.reply || "Done.", Array.isArray(chat.tool_trace) ? chat.tool_trace : []);
      } else if (!response.ok) {
        finishWorking();
        assistant(`I couldn't complete that turn: ${(answer && answer.error) || `request failed (${response.status})`}`);
      }
    }
    return response;
  } catch (problem) {
    if (isChat) {
      finishWorking();
      assistant(`I couldn't reach the Workshop agent: ${problem.message || problem}`);
    }
    throw problem;
  }
};

// Enter sends; Shift+Enter makes a new line. The browser's ordinary submit path
// remains authoritative, so accessibility and the existing CSRF/API handling
// stay intact.
textarea.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!textarea.disabled) form.requestSubmit();
  }
});
