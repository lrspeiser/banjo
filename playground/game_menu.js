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
});
$("#game-menu-close").addEventListener("click", () => dialog.close());

if (currentId && validId.test(currentId)) {
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
