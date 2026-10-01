// World links are bearer links. A browser remembers only worlds it created or
// joined; the server never publishes an index of other people's worlds.
const params = new URLSearchParams(location.search);
const currentId = params.get("world");
const validId = /^[0-9a-f]{32}$/;
const key = "banjo.known-worlds.v1";
const worldUrl = (id) => `/world?world=${id}&scene=new-game`;

function known() {
  try { return JSON.parse(localStorage.getItem(key) || "[]").filter((w) => validId.test(w.id)); }
  catch { return []; }
}
function remember(world) {
  try {
    const list = known().filter((w) => w.id !== world.id);
    list.unshift({ id: world.id, name: world.name });
    localStorage.setItem(key, JSON.stringify(list.slice(0, 30)));
  } catch { /* a private browser can still use its current link */ }
}

const dialog = document.createElement("dialog");
dialog.id = "game-menu";
dialog.innerHTML = `<div class="game-menu-head"><h2>Game menu</h2><button type="button" id="game-menu-close" aria-label="Close menu">×</button></div>
  <p id="game-menu-current">Current world</p>
  <form id="game-menu-avatar" hidden><label>Your avatar name<input name="name" maxlength="32" required></label><button type="submit">Save avatar name</button></form>
  <form id="game-menu-new"><label>World name<input name="name" maxlength="80" value="New world" required></label><button type="submit">New game · generate map</button></form>
  <form id="game-menu-join"><label>Join a world<input name="link" placeholder="Paste a world link or id" required></label><button type="submit">Join world</button></form>
  <div id="game-menu-share" hidden><p>People with this link join the same live world with their own avatar and bag.</p><button type="button" id="game-menu-copy">Copy world link</button></div>
  <section id="game-menu-ai" hidden><h3>Characters</h3><p>Watch a character follow the goal chains with its own bag, energy and tech journal.</p><form id="game-menu-ai-start"><label>Character name<input name="name" maxlength="32" value="Banjo explorer" required></label><label>Controller<select name="mode"><option value="openai">AI · OpenAI</option><option value="reference">Reference bot · no model calls</option></select></label><button type="submit">Start character</button></form><p id="game-menu-ai-status" role="status"></p><ul id="game-menu-ai-list"></ul><p>OpenAI play uses the server's configured model. Each run stops after 64 decisions, completed goal chains or a blocker. A server restart pauses characters.</p></section>
  <h3>Worlds in this browser</h3><ul id="game-menu-known"></ul><p id="game-menu-message" role="status" aria-live="polite"></p>`;
document.body.append(dialog);
const $ = (q) => dialog.querySelector(q);
const message = (text) => { $("#game-menu-message").textContent = text; };

function render() {
  const list = $("#game-menu-known");
  list.replaceChildren();
  for (const world of known()) {
    const li = document.createElement("li");
    const link = document.createElement("a");
    link.href = worldUrl(world.id);
    link.textContent = world.name || world.id;
    li.append(link);
    list.append(li);
  }
  if (!list.children.length) list.textContent = "No worlds saved in this browser yet.";
}

document.addEventListener("click", (event) => {
  if (!event.target.closest("[data-game-menu]")) return;
  render();
  dialog.showModal();
  if (currentId) loadCharacters().catch((error) => { $("#game-menu-ai-status").textContent = error.message; });
});
$("#game-menu-close").addEventListener("click", () => dialog.close());

if (currentId && validId.test(currentId)) {
  $("#game-menu-ai").hidden = false;
  $("#game-menu-avatar").hidden = false;
  $("#game-menu-avatar input").value = localStorage.getItem("banjo.avatar-name") || "Player";
  $("#game-menu-share").hidden = false;
  document.querySelector("#reset").hidden = true;
  document.querySelector("#scene").hidden = true;
  // Both static links and Workshop's dynamically made return links use this
  // world's id. The isolated Workshop still opens on the same world ledger.
  for (const link of document.querySelectorAll('a[href^="/world"]')) {
    const url = new URL(link.href);
    url.searchParams.set("world", currentId);
    if (!url.searchParams.has("workshop")) url.searchParams.set("scene", "new-game");
    link.href = url.pathname + url.search;
  }
  fetch(`/api/worlds/${currentId}`).then(async (response) => {
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "World not found");
    $("#game-menu-current").textContent = `Current world: ${data.name}`;
    remember(data);
  }).catch((error) => { $("#game-menu-current").textContent = error.message; });
}

$("#game-menu-avatar").addEventListener("submit", (event) => {
  event.preventDefault();
  const name = $("#game-menu-avatar input").value.trim();
  if (!name) return;
  localStorage.setItem("banjo.avatar-name", name);
  location.reload();
});

async function characterAction(body) {
  const player = localStorage.getItem(`banjo.player.${currentId}`);
  if (!player) throw new Error("Your character is still joining. Open Menu again when the world is ready.");
  const status = await fetch("/api/status", { headers:{ "X-Banjo-World":currentId } }).then((r) => r.json());
  const response = await fetch("/api/world/ai", { method:"POST",
    headers:{ "Content-Type":"application/json", "X-Banjo-Token":status.csrf_token,
              "X-Banjo-World":currentId, "X-Banjo-Player":player }, body:JSON.stringify(body) });
  const answer = await response.json();
  if (!response.ok) throw new Error(answer.error || "Character request failed");
  return answer;
}

async function loadCharacters() {
  const response = await characterAction({ action:"list" });
  const list = $("#game-menu-ai-list"); list.replaceChildren();
  const select = $("#game-menu-ai-start select");
  select.querySelector('[value="openai"]').disabled = !response.model_available;
  if (!response.model_available) select.value = "reference";
  $("#game-menu-ai-status").textContent = response.model_available
    ? "AI characters are ready. Reference mode is available for reproducible tests."
    : "OpenAI is not configured. Reference bots can play without model calls.";
  for (const character of response.characters) {
    const li = document.createElement("li"), label = document.createElement("p");
    li.dataset.character = character.id;
    label.textContent = `${character.name} · ${character.mode === "openai" ? "AI" : "Reference bot"} · ${character.status} · ${character.message}`;
    const watch = document.createElement("a"); watch.textContent = "Watch through its eyes";
    watch.dataset.watch = character.id;
    watch.href = `${worldUrl(currentId)}&watch=${character.id}`;
    li.append(label, watch);
    if (character.can_control && character.status !== "complete") {
      const running = ["running", "thinking", "walking"].includes(character.status);
      const control = document.createElement("button"); control.type = "button";
      control.textContent = running ? "Pause" : "Resume";
      control.onclick = async () => {
        control.disabled = true;
        try { await characterAction({ action:running ? "pause" : "start", id:character.id }); await loadCharacters(); }
        catch (error) { $("#game-menu-ai-status").textContent = error.message; control.disabled = false; }
      };
      li.append(control);
    }
    list.append(li);
  }
  if (!list.children.length) list.textContent = "No characters started in this world yet.";
}

$("#game-menu-ai-start").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#game-menu-ai-start button"); button.disabled = true;
  try {
    const character = await characterAction({ action:"start", name:$("#game-menu-ai-start input").value.trim(),
                                            mode:$("#game-menu-ai-start select").value });
    location.assign(`${worldUrl(currentId)}&watch=${character.id}`);
  } catch (error) { $("#game-menu-ai-status").textContent = error.message; button.disabled = false; }
});

setInterval(() => {
  if (dialog.open && currentId && !document.hidden) loadCharacters().catch(() => {});
}, 3000);

$("#game-menu-copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(new URL(worldUrl(currentId), location.origin).href);
    message("World link copied.");
  } catch { message("Copy the address from your browser's address bar."); }
});

$("#game-menu-new").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#game-menu-new button");
  button.disabled = true;
  message("Generating and checking a new map…");
  try {
    const status = await fetch("/api/status").then((r) => r.json());
    const response = await fetch("/api/worlds", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Banjo-Token": status.csrf_token },
      body: JSON.stringify({ name: $("#game-menu-new input").value.trim() }),
    });
    const answer = await response.json();
    if (!response.ok) throw new Error(answer.error || "Map generation failed");
    remember(answer);
    location.assign(answer.url);
  } catch (error) { message(error.message || String(error)); button.disabled = false; }
});

$("#game-menu-join").addEventListener("submit", async (event) => {
  event.preventDefault();
  const supplied = $("#game-menu-join input").value.trim();
  let id = supplied;
  try { id = new URL(supplied, location.origin).searchParams.get("world") || supplied; }
  catch { /* an id is also accepted */ }
  if (!validId.test(id)) { message("Paste a Banjo world link or 32-character world id."); return; }
  try {
    const response = await fetch(`/api/worlds/${id}`);
    const world = await response.json();
    if (!response.ok) throw new Error(world.error || "World not found");
    remember(world);
    location.assign(worldUrl(id));
  } catch (error) { message(error.message || String(error)); }
});

render();

// The same screen navigation in the world and Workshop, preserving the game
// and an explicitly selected carried item. Selection is revalidated by Lab.
export const SCREENS = [["world", "World"], ["inventory", "Inventory"], ["lab", "Lab"],
  ["skills", "Skills"], ["recipes", "Recipes"], ["market", "Market"], ["goals", "Goals"]];

export function screenUrl(screen) {
  const current = new URLSearchParams(location.search), query = new URLSearchParams();
  for (const key of ["world", "scene", "carry", "design", "library"]) if (current.get(key)) query.set(key, current.get(key));
  if (screen !== "world") { query.set("workshop", "1"); query.set("tab", screen); }
  return `/world${query.size ? "?" + query : ""}`;
}

export function gameNavigation(active, onSelect = null) {
  const nav = document.createElement("nav");
  nav.className = "game-tabs ws-tabs"; nav.setAttribute("aria-label", "Game screens");
  if (onSelect) nav.setAttribute("role", "tablist");
  for (const [name, label] of SCREENS) {
    const local = onSelect && name !== "world";
    const tab = document.createElement(local ? "button" : "a");
    tab.textContent = label; tab.dataset.screen = name; tab.dataset.tab = name;
    if (local) {
      tab.type = "button"; tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", name === "lab" ? "ws-centre" : `ws-pane-${name}`);
      tab.setAttribute("aria-selected", String(name === active));
      tab.onclick = () => onSelect(name);
    } else {
      tab.href = screenUrl(name);
      if (name === active) tab.setAttribute("aria-current", "page");
      if (name === "inventory") tab.classList.add("workshop-entry");
      if (name === "goals") tab.classList.add("goals-entry");
      if (name === "market") tab.classList.add("market-entry");
    }
    nav.append(tab);
  }
  return nav;
}

export function refreshNavigation(active) {
  for (const tab of document.querySelectorAll(".game-tabs [data-screen]")) {
    if (tab.tagName === "A") tab.href = screenUrl(tab.dataset.screen);
    else tab.setAttribute("aria-selected", String(tab.dataset.screen === active));
  }
}

export function showSaveStatus(status) {
  if (!status) return;
  let banner = document.getElementById("world-save-status");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "world-save-status";
    banner.setAttribute("role", "status");
    const rail = document.body.classList.contains("workshop-mode")
      ? document.querySelector(".ws-left") : document.getElementById("panel");
    rail?.prepend(banner);
  }
  banner.hidden = status.state !== "failed";
  if (!banner.hidden) {
    banner.textContent = "World not saved. " + (status.reason || "Saving failed.") + " Progress since the last save is still pending.";
  }
}
