# Mobile controls and deliberate panels — October 6, 2026

UI changes based on main `f5b52dcbf3fd9846a2e8924df9be93ebc4c6f598`. Native binaries, material laws and private game saves are unchanged.

## Player behavior

- The movement pad sits above the actual menu, inventory and hand-card bounds in its left-side lane. It updates after orientation/viewport changes and inventory resizing, respects the left safe area and appears on the first touch even when the cursor is free.
- The main-world sidebar is folded in the initial HTML. Slow or failed JavaScript downloads cannot briefly display it. Chat opens through the Chat button, slash key or an explicit voice interaction; reload starts folded.
- The map, target/material preview and extended inventory/movement help live inside Details. They no longer appear automatically as floating boxes over the world. The surface readiness marker and actual tool actions retain their existing path.

## Verification

[World navigation regression](../tests/world_navigation_tests.py) checks the initial painted layout with JavaScript disabled, watches for unwanted sidebar frames during native startup and reload, and exercises actual touch events at 390×844, 844×390, 360×640 and 1280×800. It checks menu/inventory separation and touch hit testing across the pad, actual movement in the existing camera walk mode, explicit Details/Chat disclosure and console exceptions. Shared Workshop chat remains usable at desktop and portrait sizes; World's folded state does not shrink its width. CI already runs this file with required browser prerequisites. Both navigation methods pass in **13.897 s** on Windows Chrome against the unchanged native Release bundle. The log retains a Windows aborted HTTP connection during page navigation; no browser runtime exceptions were observed. JavaScript syntax, diff whitespace and the **304/304** source-registration guard pass.

Screenshots and the scoped run log are under `build/resource-flow/mobile-hud-*.png` and `build/mobile-hud-regression.log`; these are local test artifacts. Portrait and landscape screenshots were visually reviewed. This is Windows Chrome viewport/touch emulation, not physical iPhone/Android acceptance or native locomotion qualification. The separate full regression audit remains unresolved.

## Publication and demo

Implementation `a2e6a93e29507eab11b2c05b04d9da30cbf4d2f9` is published on GitHub main and installed in the local `C:/play` checkout. HTTP checks confirm that port 18890 serves the matching HTML, CSS and JavaScript and reports `engine_ready: true`. This static UI update retained server PID 21676 and its existing native sessions; no restart or private-save conversion was needed. [Refresh the test world](http://localhost:18890/world?world=c7c8058545c1492eb69f4dbcbb86edfc&scene=new-game) to load it.
