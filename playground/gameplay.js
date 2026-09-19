import * as THREE from "/vendor/three.module.js";

// These are surface-stock and camp markers, not colliding rigid machine parts.
export function expeditionUI({scene, camera, request, pause, isPaused, wait, sun}) {
  const panel = document.createElement("section");
  panel.id = "expedition";
  panel.hidden = true;
  document.querySelector("#panel header").after(panel);
  const title = document.createElement("h2");
  title.textContent = "A place to begin";
  const intro = document.createElement("p");
  intro.textContent = "Walk to the coloured surface stocks. Gather stone and dry wood, build the camp, then dry a batch of wet timber.";
  const status = document.createElement("p");
  const pack = document.createElement("p");
  const process = document.createElement("p");
  const stocks = document.createElement("div");
  const controls = document.createElement("div");
  const notice = document.createElement("p");
  notice.setAttribute("role", "status");
  panel.append(title, intro, status, pack, process, stocks, controls, notice);
  const group = new THREE.Group();
  scene.add(group);
  const colours = {stone: 0xc3c9c9, dry_wood: 0xf0b458, wet_wood: 0x71c6b9};
  const names = {stone: "loose stone", dry_wood: "dry branches", wet_wood: "wet timber"};
  let state = null, busy = false, stopped = false, drawn = "";
  const originalSun = {position: sun.position.clone(), intensity: sun.intensity};
  const originalSky = scene.background.clone();
  const buttons = [];
  function button(label, action, parent=controls) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", action);
    parent.append(b);
    buttons.push(b);
    return b;
  }
  async function act(action, extra={}) {
    if (busy || !state) return;
    busy = true;
    notice.textContent = "Saving…";
    try {
      const answer = await request({action, request_id: crypto.randomUUID(),
                                    at_m: camera.position.toArray(), ...extra});
      update(answer.gameplay);
      notice.textContent = "Saved.";
    } catch (error) { notice.textContent = error.message; }
    finally { busy = false; refresh(); }
  }
  button("Build camp · 2 kg stone + 0.5 kg wood", () => act("build"));
  button("Load 1 kg wet timber", () => act("load", {kg: 1}));
  button("Add 0.2 kg fuel", () => act("fuel", {kg: 0.2}));
  button("Light fire", () => act("light"));
  button("Extinguish", () => act("extinguish"));
  button("Collect dry timber", () => act("collect"));
  const pauseButton = button("Pause world", () => {
    if (busy) { stopped = true; return; }
    pause(!isPaused());
    refresh();
  });
  button("Wait 30 world seconds", async () => {
    if (busy) return;
    busy = true;
    stopped = false;
    const wasPaused = isPaused();
    pause(true);
    try {
      for (let i=0; i<30 && !stopped && state && !document.hidden; i++) {
        const answer = await wait();
        update(answer.gameplay);
        notice.textContent = `Waited ${i+1} / 30 seconds. Pause stops waiting.`;
      }
    } catch (error) { notice.textContent = error.message; }
    finally { busy = false; pause(wasPaused); refresh(); }
  });
  function marker(at, colour, radius) {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, 0.05, 16),
                               new THREE.MeshStandardMaterial({color: colour, emissive: colour, emissiveIntensity: 0.2}));
    mesh.position.set(at[0], at[1]+0.07, at[2]);
    group.add(mesh);
  }
  function refresh() {
    if (!state) return;
    const c = state.clock;
    status.textContent = `Day ${c.day} · ${c.elapsed_s.toFixed(1)} seconds · ${isPaused() ? "paused" : "live"}`;
    pack.textContent = "Material pack · " + Object.entries(state.inventory_kg)
      .map(([kind, kg]) => `${kg.toFixed(2)} kg ${names[kind]}`).join(" · ");
    const d = state.dryer;
    process.textContent = d
      ? `Camp: ${d.condition} · ${(d.temperature_k-273.15).toFixed(1)} °C · ${d.fuel_kg.toFixed(3)} kg fuel · ${d.water_kg.toFixed(3)} kg water left · ${d.wood_kg.toFixed(2)} kg timber`
      : "Camp is unbuilt. Gold ring marks its site.";
    pauseButton.textContent = busy ? "Stop waiting" : isPaused() ? "Resume world" : "Pause world";
    for (const b of buttons) b.disabled = busy && b !== pauseButton;
    for (const b of stocks.querySelectorAll("button")) {
      const n = state.nodes.find(n => n.id === b.dataset.node);
      const distance = Math.hypot(camera.position.x-n.at_m[0], camera.position.z-n.at_m[2]);
      b.textContent = `${names[n.kind]} · ${n.kg.toFixed(1)} kg · ${distance.toFixed(1)} m — gather 1 kg`;
      b.disabled = busy || n.kg < 1 || distance > 2.5;
    }
  }
  function update(next) {
    if (!state && !next) return;
    state = next || null;
    panel.hidden = !state;
    document.getElementById("talk").hidden = !!state;
    document.getElementById("details").hidden = !!state;
    group.visible = !!state;
    if (!state) {
      sun.position.copy(originalSun.position); sun.intensity = originalSun.intensity;
      scene.background.copy(originalSky);
      return;
    }
    scene.background.set(0x567888);
    const layout = JSON.stringify(state.nodes.map(n => [n.id, n.at_m]));
    if (drawn !== layout) {
      for (const m of [...group.children]) {
        group.remove(m); m.geometry.dispose(); m.material.dispose();
      }
      stocks.replaceChildren();
      marker(state.camp_m, 0xffd46f, 0.6);
      for (const n of state.nodes) {
        marker(n.at_m, colours[n.kind], 0.25);
        const b = button("", () => act("gather", {node: n.id, kg: 1}), stocks);
        b.dataset.node = n.id;
      }
      drawn = layout;
    }
    group.children.slice(1).forEach((m, i) => { m.visible = state.nodes[i].kg > 0; });
    // Sun phase affects presentation only. It never scales machine elapsed time.
    const angle = state.clock.day_fraction * Math.PI * 2;
    sun.position.set(Math.cos(angle)*20, Math.sin(angle)*20, 8);
    sun.intensity = Math.max(0.1, Math.sin(angle)*1.6);
    refresh();
  }
  setInterval(refresh, 250);
  return {update};
}
