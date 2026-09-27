// Debug: the bench the coding agents work from.
//
// Everything on the page is read from the server as it loads. Nothing about the
// rooms or the suites is written down here: a list of scenes in a page goes
// stale the moment world_room.SCENES moves and cannot be told that it has, so
// the page asks. The only things spelled out below are the words for what a
// field MEANS, which is the one thing the API cannot say.

const $ = (id) => document.getElementById(id);

async function get(path) {
  const reply = await fetch(path, { headers: { Accept: "application/json" } });
  const body = await reply.json().catch(() => ({ error: `${reply.status} ${reply.statusText}` }));
  if (!reply.ok) throw new Error(body.error || `${reply.status} ${reply.statusText}`);
  return body;
}

async function post(path, body) {
  const status = await get("/api/status");
  const reply = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Banjo-Token": status.csrf_token },
    body: JSON.stringify(body),
  });
  const answer = await reply.json().catch(() => ({ error: `${reply.status} ${reply.statusText}` }));
  if (!reply.ok) throw new Error(answer.error || `${reply.status} ${reply.statusText}`);
  return answer;
}

function fact(label, value, kind) {
  const box = document.createElement("div");
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.textContent = value;
  if (kind) dd.className = `status ${kind}`;
  box.append(dt, dd);
  return box;
}

const yesNo = (flag) => (flag ? "yes" : "no");
const goodBad = (flag) => (flag ? "good" : "bad");

// ---- The engine ------------------------------------------------------------

async function showEngine() {
  const facts = $("engine-facts");
  try {
    const status = await get("/api/status");
    facts.replaceChildren(
      fact("Engine", yesNo(status.engine_ready), goodBad(status.engine_ready)),
      fact("Studio", yesNo(status.studio_ready), status.studio_ready ? "good" : "warn"),
      fact("Room open", yesNo(status.world_room_open)),
      fact("Chat model", status.model || "none"),
      fact("Chat key", yesNo(status.key_configured), status.key_configured ? "good" : "warn"),
      fact("Jev", yesNo(status.jev_configured), status.jev_configured ? "good" : "warn"),
      fact("Capabilities", (status.capabilities || []).length),
    );
    const limits = status.limitations || [];
    $("engine-limits").textContent = limits.length
      ? `What it will not claim: ${limits.join(" ")}`
      : "";
  } catch (err) {
    facts.replaceChildren(fact("Status", String(err.message || err), "bad"));
  }
}

// ---- The rooms -------------------------------------------------------------

// A trial room is one built to measure something; the rest are places. The
// prefix is the server's own naming, not a guess about the contents.
function groupScenes(scenes) {
  const trials = scenes.filter((name) => name.startsWith("tests-"));
  const places = scenes.filter((name) => !name.startsWith("tests-"));
  return [
    ["Places", places],
    ["Trial rooms", trials],
  ].filter(([, names]) => names.length);
}

async function showRooms() {
  const host = $("rooms-list");
  try {
    const { scenes = [] } = await get("/api/scenes");
    const parts = [];
    for (const [title, names] of groupScenes(scenes)) {
      const group = document.createElement("div");
      group.className = "dbg-group";
      const head = document.createElement("h3");
      head.textContent = `${title} · ${names.length}`;
      const list = document.createElement("ul");
      list.className = "dbg-rooms";
      for (const name of names) {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = `/world?scene=${encodeURIComponent(name)}`;
        link.textContent = name;
        item.append(link);
        list.append(item);
      }
      group.append(head, list);
      parts.push(group);
    }
    host.replaceChildren(...parts);
  } catch (err) {
    const said = document.createElement("p");
    said.className = "note status bad";
    said.textContent = String(err.message || err);
    host.replaceChildren(said);
  }
}

// ---- The QA suites ---------------------------------------------------------

const SUITES = [
  {
    id: "material-qa",
    title: "Material QA",
    why: "A plate of one material struck at one speed, against the band it is expected to fall in.",
    needs: "banjo_fast_lattice_run beside the engine",
  },
  {
    id: "mechanics-qa",
    title: "Mechanics QA",
    why: "Whole-body trials: what holds, what carries, what gives way.",
    needs: "the native live world runner",
  },
  {
    id: "tool-qa",
    title: "Tool QA",
    why: "A tool into ground: what the head does and what the ground does back.",
    needs: "the native live world runner",
  },
];

function caseLabel(entry) {
  const words = [entry.id];
  if (entry.title && entry.title !== entry.id) words.push(`— ${entry.title}`);
  else if (entry.group) words.push(`— ${entry.group}`);
  return words.join(" ");
}

function renderRuns(host, runs) {
  if (!runs.length) {
    host.replaceChildren();
    return;
  }
  const items = runs.slice(0, 5).map((run) => {
    const item = document.createElement("li");
    const left = document.createElement("span");
    left.textContent = run.id ? run.id.slice(0, 8) : "—";
    const right = document.createElement("span");
    right.className = `status ${run.status === "passed" ? "good" : run.status === "failed" ? "bad" : "warn"}`;
    right.textContent = `${run.status || "?"} · ${run.completed ?? 0}/${run.total ?? 0}`;
    item.append(left, right);
    return item;
  });
  host.replaceChildren(...items);
}

async function showSuite(suite) {
  const card = document.createElement("section");
  card.className = "dbg-suite";

  const head = document.createElement("h3");
  head.textContent = suite.title;
  const why = document.createElement("p");
  why.className = "why";
  why.textContent = suite.why;
  const facts = document.createElement("dl");
  facts.className = "dbg-facts";
  const row = document.createElement("div");
  row.className = "dbg-row";
  const said = document.createElement("p");
  said.className = "dbg-said";
  const runs = document.createElement("ul");
  runs.className = "dbg-results";
  card.append(head, why, facts, row, said, runs);

  let catalog;
  try {
    catalog = await get(`/api/${suite.id}`);
  } catch (err) {
    facts.replaceChildren(fact("Catalog", String(err.message || err), "bad"));
    return card;
  }

  const cases = catalog.cases || [];
  const hash = catalog.suite_hash || catalog.fixture_hash || "—";
  const runnable = Boolean(catalog.engine_available);
  facts.replaceChildren(
    fact("Cases", cases.length),
    fact("Can run here", yesNo(runnable), goodBad(runnable)),
    fact("Suite hash", String(hash).slice(0, 12)),
  );

  const pick = document.createElement("select");
  pick.setAttribute("aria-label", `Which ${suite.title} case`);
  for (const entry of cases) {
    const option = document.createElement("option");
    option.value = entry.id;
    option.textContent = caseLabel(entry);
    pick.append(option);
  }
  const run = document.createElement("button");
  run.type = "button";
  run.textContent = "Run this case";
  row.append(pick, run);

  // Its own line, not another item in the row: at a middling card width the
  // row would rather clip this than wrap it, and a clipped link is a bug you
  // only see at one window size.
  const catalogLine = document.createElement("p");
  catalogLine.className = "dbg-links";
  const catalogLink = document.createElement("a");
  catalogLink.href = `/api/${suite.id}`;
  catalogLink.textContent = "catalog JSON";
  catalogLine.append(catalogLink);
  card.insertBefore(catalogLine, said);

  if (!runnable) {
    run.disabled = true;
    said.textContent = `Not built here — needs ${suite.needs}.`;
  }

  const refresh = async () => {
    try {
      const listed = await get(`/api/${suite.id}/runs`);
      renderRuns(runs, listed.runs || []);
      return listed.runs || [];
    } catch {
      return [];
    }
  };
  await refresh();

  run.addEventListener("click", async () => {
    run.disabled = true;
    said.textContent = `Running ${pick.value}…`;
    said.className = "dbg-said";
    try {
      const started = await post(`/api/${suite.id}/run`, { case_ids: [pick.value] });
      const id = started.id;
      // The run is a thread on the server; the report is the only truth about
      // it, so this asks for the report rather than assuming the thread's pace.
      for (let tick = 0; tick < 300; tick += 1) {
        await new Promise((done) => setTimeout(done, 1000));
        let report;
        try {
          report = await get(`/api/${suite.id}/runs/${id}`);
        } catch (err) {
          said.textContent = String(err.message || err);
          said.className = "dbg-said status bad";
          break;
        }
        said.textContent = `${report.status} · ${report.completed ?? 0}/${report.total ?? 0}`;
        await refresh();
        if (report.status && !["starting", "running"].includes(report.status)) {
          said.className = `dbg-said status ${report.status === "passed" ? "good" : report.status === "failed" ? "bad" : "warn"}`;
          break;
        }
      }
    } catch (err) {
      said.textContent = String(err.message || err);
      said.className = "dbg-said status bad";
    } finally {
      run.disabled = false;
    }
  });

  return card;
}

async function showSuites() {
  const host = $("suites-list");
  const cards = await Promise.all(SUITES.map((suite) => showSuite(suite)));
  host.replaceChildren(...cards);
}

// ---- The routes ------------------------------------------------------------

const ROUTES = [
  ["GET /api/status", "What the engine and the chat are set up with, and the token every POST needs."],
  ["GET /api/scenes", "Every room this server can open."],
  ["GET /api/materials", "What each material is, from the engine's own catalogue."],
  ["GET /api/material-qa", "The material suite: its cases, speeds and expected bands."],
  ["GET /api/mechanics-qa", "The whole-body trials, each with its document."],
  ["GET /api/tool-qa", "The tool-into-ground cases."],
  ["GET /api/fabrication-qa/runs", "Fabrication runs on this server."],
  ["GET /api/<suite>/runs/<id>", "One run's report. <suite> is material-qa, mechanics-qa or tool-qa."],
  ["POST /api/world/open", "Open a room: {\"scene\": \"world\"}."],
  ["POST /api/live/act", "Step it: {\"session\", \"op\": \"step\", \"dt\", \"n\"}."],
  ["POST /api/<suite>/run", "Start a suite: {\"case_ids\": [...]}, or omit for all of it."],
];

function showRoutes() {
  const host = $("routes-list");
  host.replaceChildren(...ROUTES.map(([route, what]) => {
    const item = document.createElement("li");
    const code = document.createElement("code");
    code.textContent = route;
    const said = document.createElement("span");
    said.textContent = what;
    item.append(code, said);
    return item;
  }));
}

showRoutes();
await Promise.all([showEngine(), showRooms(), showSuites()]);
