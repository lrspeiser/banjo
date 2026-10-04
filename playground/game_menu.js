import {materialAppearance, samplePattern} from "./material_appearance.js";

// World links are bearer links. A browser remembers only worlds it created or
// joined; the server never publishes an index of other people's worlds.
const params = new URLSearchParams(location.search);
const currentId = params.get("world");
const validId = /^[0-9a-f]{32}$/;
const key = "banjo.known-worlds.v1";
const worldUrl = (id) => `/world?world=${id}&scene=new-game`;

// A plain game entry creates a generated world. Explicit scene/QA links remain
// available to the laboratory and saved-world links always rejoin their world.
export async function enterGame() {
  if (currentId || params.has("scene") || params.has("qa")) return true;
  const state = document.querySelector("#panel-state");
  if (state) state.textContent = "Generating your world…";
  try {
    const status = await fetch("/api/status").then(r => r.json());
    const response = await fetch("/api/worlds", {method:"POST",
      headers:{"Content-Type":"application/json", "X-Banjo-Token":status.csrf_token},
      body:JSON.stringify({name:"New world"})});
    const answer = await response.json();
    if (!response.ok) throw new Error(answer.error || "Map generation failed");
    remember(answer);
    const target = new URL(answer.url, location.origin);
    // Keep where the link was going. A rung of the tree or a catalog recipe
    // exists in every world; a saved design, carried item or job belongs to
    // the world it was made in, so those are not carried into a new one.
    for (const key of ["workshop", "tab", "technique", "recipe"]) if (params.has(key)) target.searchParams.set(key, params.get(key));
    location.replace(target.pathname + target.search);
  } catch (error) {
    if (state) state.textContent = `Could not start: ${error.message}. Use Menu → New game to retry.`;
  }
  return false;
}

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
  <label id="game-menu-movement">Movement<select><option value="native">Body · walk, swim, carry</option><option value="fly">God mode · fly freely</option><option value="gravity">Camera · walk without a body</option></select></label>
  <form id="game-menu-avatar" hidden><label>Your avatar name<input name="name" maxlength="32" required></label><button type="submit">Save avatar name</button></form>
  <form id="game-menu-new"><label>World name<input name="name" maxlength="80" value="New world" required></label><label>Ground<select name="surface"><option value="cuts">Smooth hills · sharp cuts · preview</option><option value="smooth" selected>Smooth slopes</option><option value="columns">Material cells · preview</option><option value="columns-fine">Material cells · 12.5 cm · preview</option></select></label><button type="submit">New game · generate map</button></form>
  <form id="game-menu-join"><label>Join a world<input name="link" placeholder="Paste a world link or id" required></label><button type="submit">Join world</button></form>
  <div id="game-menu-share" hidden><p>People with this link join the same live world with their own avatar and bag.</p><button type="button" id="game-menu-copy">Copy world link</button></div>
  <section id="game-menu-ai" hidden><h3>Characters</h3><p>Watch a character follow the goal chains with its own bag, energy and tech journal.</p><form id="game-menu-ai-start"><label>Character name<input name="name" maxlength="32" value="Banjo explorer" required></label><label>Controller<select name="mode"><option value="openai">AI · OpenAI</option><option value="reference">Reference bot · no model calls</option></select></label><button type="submit">Start character</button></form><p id="game-menu-ai-status" role="status"></p><ul id="game-menu-ai-list"></ul><p>OpenAI play uses the server's configured model. Each run stops after 64 decisions, completed goal chains or a blocker. A server restart pauses characters.</p></section>
  <h3>Worlds in this browser</h3><ul id="game-menu-known"></ul><p id="game-menu-message" role="status" aria-live="polite"></p>`;
document.body.append(dialog);
const $ = (q) => dialog.querySelector(q);
const message = (text) => { $("#game-menu-message").textContent = text; };
const movementSelect = $("#game-menu-movement select");
movementSelect.value = localStorage.getItem("banjo.movement") || "native";
movementSelect.addEventListener("change", () => {
  localStorage.setItem("banjo.movement", movementSelect.value);
  dispatchEvent(new CustomEvent("banjo-movement-mode", {detail:movementSelect.value}));
  dialog.close();
});

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
      body: JSON.stringify({ name: $("#game-menu-new input").value.trim(),surface:$("#game-menu-new select").value }),
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
  for (const key of ["world", "scene", "carry", "design", "library", "recipe"]) if (current.get(key)) query.set(key, current.get(key));
  if (screen !== "world") { query.set("workshop", "1"); query.set("tab", screen); }
  return `/world${query.size ? "?" + query : ""}`;
}

export function gameNavigation(active, onSelect = null) {
  const nav = document.createElement("nav");
  nav.className = "game-tabs ws-tabs game-bottom-tabs"; nav.setAttribute("aria-label", "Game screens");
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

// Shared material/product icons for full and compact Inventory.
export function massLabel(kg) {
  const value=Number(kg) || 0, magnitude=Math.abs(value);
  const unit=magnitude>=1000?"t":magnitude>=1 || !magnitude?"kg":"g";
  const amount=unit==="t"?value/1000:unit==="g"?value*1000:value;
  return `${amount.toLocaleString(undefined,{maximumFractionDigits:2})} ${unit}`;
}
export function thumbnail(thing) {
  const canvas = document.createElement("canvas"), size = 48, m = 8, w = 32;
  canvas.width = canvas.height = size;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", `${thing.label || thing.name}, ${thing.material || "item"}`);
  const pen = canvas.getContext("2d");
  if (!pen) return canvas;
  const appearance=materialAppearance(thing.material);
  const hex = appearance?.color || (/^[0-9a-f]{6,8}$/i.test(thing.color_rgba || "") ? thing.color_rgba.slice(0,6) : "9aa7b4");
  const dark = amount => {
    const n = parseInt(hex,16), mix = c => Math.max(0,Math.min(255,Math.round(c*amount)));
    return `rgb(${mix((n>>16)&255)},${mix((n>>8)&255)},${mix(n&255)})`;
  };
  const face = `#${hex}`;
  if (thing.shape === "granules") {
    // A material sample, distinct from a manufactured product's silhouette.
    for (let i=0;i<14;i++) {
      const x=9+(i*13%30), y=37-Math.floor(i/5)*9;
      pen.fillStyle=i%3 ? face : dark(.65);
      pen.beginPath(); pen.moveTo(x,y-6);pen.lineTo(x+6,y-2);
      pen.lineTo(x+4,y+4);pen.lineTo(x-3,y+3);pen.closePath();pen.fill();
      if(appearance) {
        pen.save();pen.clip();samplePattern(pen,appearance,x-3,y-6,9,10);pen.restore();
      }
    }
  } else if (thing.shape === "sphere" || thing.shape === "capsule") {
    const light = pen.createRadialGradient(18,17,2,24,24,16);
    light.addColorStop(0,face); light.addColorStop(1,dark(.45)); pen.fillStyle=light;
    pen.beginPath(); pen.arc(24,24,16,0,Math.PI*2); pen.fill();
  } else if (thing.shape === "cylinder") {
    pen.fillStyle=dark(.7); pen.fillRect(m,m+5,w,w-10); pen.fillStyle=face;
    pen.beginPath(); pen.ellipse(24,m+5,16,5,0,0,Math.PI*2); pen.fill(); pen.fillStyle=dark(.5);
    pen.beginPath(); pen.ellipse(24,35,16,5,0,0,Math.PI*2); pen.fill();
  } else {
    pen.fillStyle=face; pen.fillRect(m,15,25,25);
    if(appearance)samplePattern(pen,appearance,m,15,25,25);
    pen.fillStyle=dark(1.25);
    pen.beginPath(); pen.moveTo(8,15); pen.lineTo(15,8); pen.lineTo(40,8); pen.lineTo(33,15); pen.closePath(); pen.fill();
    pen.fillStyle=dark(.6); pen.beginPath(); pen.moveTo(33,15); pen.lineTo(40,8);
    pen.lineTo(40,33); pen.lineTo(33,40); pen.closePath(); pen.fill();
  }
  return canvas;
}
