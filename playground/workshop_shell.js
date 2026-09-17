const $ = (q, root = document) => root.querySelector(q);
const $$ = (q, root = document) => [...root.querySelectorAll(q)];

function el(tag, attrs = {}, text = "") {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "hidden") node.hidden = Boolean(value);
    else node.setAttribute(key, String(value));
  }
  if (text) node.textContent = text;
  return node;
}

async function waitFor(selector, timeoutMs = 8000) {
  const found = $(selector);
  if (found) return found;
  return await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { observer.disconnect(); reject(new Error(`Workshop shell timed out waiting for ${selector}`)); }, timeoutMs);
    const observer = new MutationObserver(() => {
      const node = $(selector);
      if (!node) return;
      clearTimeout(timer); observer.disconnect(); resolve(node);
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  });
}

function syncCardSelection(select, cards) {
  for (const card of cards) card.setAttribute("aria-current", card.dataset.value === select.value ? "true" : "false");
}

function cardifySelect(select, root, className, description) {
  const render = () => {
    root.replaceChildren();
    const cards = [];
    for (const option of [...select.options]) {
      const card = el("button", { type: "button", class: className, "data-value": option.value });
      card.append(el("strong", {}, option.textContent || option.value));
      card.append(el("small", {}, description(option)));
      card.addEventListener("click", () => {
        if (select.value !== option.value) {
          select.value = option.value;
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
        syncCardSelection(select, cards);
      });
      cards.push(card); root.append(card);
    }
    syncCardSelection(select, cards);
  };
  render();
  select.addEventListener("change", () => syncCardSelection(select, $$("button", root)));
  new MutationObserver(render).observe(select, { childList: true, subtree: true });
}

function foldDirectSection(root, headingText, summaryText = headingText) {
  const heading = $$(":scope > h2", root).find(node => node.textContent.trim().toLowerCase() === headingText.toLowerCase());
  if (!heading) return null;
  const details = el("details", { class: "ws-fold" });
  details.append(el("summary", {}, summaryText));
  const body = el("div", { class: "ws-fold-body" });
  let node = heading.nextSibling;
  heading.remove();
  while (node) {
    const next = node.nextSibling;
    if (node.nodeType === Node.ELEMENT_NODE && node.tagName === "H2") break;
    body.append(node); node = next;
  }
  details.append(body);
  root.append(details);
  return details;
}

function moveHeadingBlock(root, title, destination) {
  const headings = $$(":scope > h3", root);
  const heading = headings.find(node => node.textContent.trim().toLowerCase() === title.toLowerCase());
  if (!heading) return;
  let node = heading;
  while (node) {
    const next = node.nextSibling;
    if (node !== heading && node.nodeType === Node.ELEMENT_NODE && node.tagName === "H3") break;
    destination.append(node); node = next;
  }
}

function makeTabs(right, panes) {
  const nav = el("div", { class: "ws-workspace-tabs", role: "tablist", "aria-label": "Workshop mode" });
  const activate = name => {
    for (const [key, pane] of Object.entries(panes)) pane.hidden = key !== name;
    for (const button of $$("button", nav)) button.setAttribute("aria-selected", button.dataset.mode === name ? "true" : "false");
  };
  for (const [name, label] of [["build", "Build"], ["test", "Test"], ["details", "Details"]]) {
    const button = el("button", { type: "button", role: "tab", "data-mode": name, "aria-selected": name === "build" ? "true" : "false" }, label);
    button.addEventListener("click", () => activate(name)); nav.append(button);
  }
  const metrics = $(".ws-metrics", right); (metrics || $("#ws-purpose", right)).after(nav);
  activate("build");
}

async function install() {
  if (!new URLSearchParams(location.search).has("workshop")) return;
  await Promise.all([waitFor("#ws-user-library"), waitFor("#ws-test-bench"), waitFor("#ws-component-editor")]);

  const left = $(".ws-left");
  const right = $(".ws-right");
  const archetype = $("#ws-archetype");
  if (!left || !right || !archetype || $("#ws-product-catalog")) return;

  const nativeLabel = archetype.closest("label");
  if (nativeLabel) nativeLabel.classList.add("ws-native-picker-hidden");

  const products = el("section", { class: "ws-product-section" });
  products.append(el("h2", {}, "Product library"));
  products.append(el("p", {}, "Open a product to design, test, or fork it. The object list stays visible instead of hiding behind a dropdown."));
  const productCatalog = el("div", { id: "ws-product-catalog", class: "ws-product-catalog" });
  products.append(productCatalog); left.prepend(products);
  cardifySelect(archetype, productCatalog, "ws-product-card", option => `Open ${option.textContent || option.value} in the Workshop`);

  const personal = $("#ws-user-library")?.parentElement;
  if (personal) products.after(personal);

  foldDirectSection(left, "Variants", "Variants");
  foldDirectSection(left, "Saved designs", "Saved designs");
  foldDirectSection(left, "Library", "Component families");

  const build = el("div", { id: "ws-mode-build", class: "ws-mode-pane" });
  const test = el("div", { id: "ws-mode-test", class: "ws-mode-pane", hidden: true });
  const details = el("div", { id: "ws-mode-details", class: "ws-mode-pane", hidden: true });

  const editor = $("#ws-component-editor"); if (editor) build.append(editor);
  moveHeadingBlock(right, "Components", build);

  const testBench = $("#ws-test-bench");
  if (testBench) {
    test.append(el("p", { class: "ws-test-intro" }, "Run isolated product tests here. These trials never advance or mutate the outside world."));
    test.append(testBench);
    const picker = $("#ws-bench-test", testBench);
    if (picker) {
      const pickerLabel = picker.closest("label"); if (pickerLabel) pickerLabel.classList.add("ws-native-picker-hidden");
      const catalog = el("div", { id: "ws-test-catalog", class: "ws-test-catalog" });
      const controls = $("#ws-bench-controls", testBench); (controls || testBench.firstChild).before(catalog);
      cardifySelect(picker, catalog, "ws-test-card", option => {
        const spec = option.value && window.__banjoWorkshopBenchTests?.find?.(item => item.test === option.value);
        return spec?.about || "Run this test on the selected product";
      });
    }
  }
  moveHeadingBlock(right, "Cheap checks", test);

  const bom = $("#ws-bom")?.parentElement; if (bom) details.append(bom);
  moveHeadingBlock(right, "Save design", details);
  moveHeadingBlock(right, "Feedback", details);
  moveHeadingBlock(right, "Materialization", details);

  right.append(build, test, details);
  makeTabs(right, { build, test, details });
}

install().catch(error => console.warn("Workshop shell:", error));
