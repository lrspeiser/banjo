# Complete Market guidance — September 30, 2026

Published implementation: **main**,
`d7571fb7b2a505e4c406b2f2be8be8467c032d1b`.

## Player flow

Market now shows the next personally reachable skill, its actual equipment and
action, and an Open skill button. If no supported route is available, it names
the missing prerequisite or equipment instead of saying the tree is finished.

A recommended build has a thumbnail, associated goal, preceding checklist
steps, all material/goods requirements, a complete stock cost estimate and an
energy shortfall. Covered lines stay visible beside missing lines. Open recipe
clears the material filter and highlights the exact card; it does not make the
item or grant learning. Stock, source and predicted personal/shared debit
details are folded. Prices and estimates are folded too.

The opening purchase goal and recipe funding are separate. Shared stock can
fund the stool, while the checklist still requires personal purchases. The
screen labels **Build stock estimate** and **Goal stock estimate** separately.
Purchases enter personal stock; normal Make still spends personal stock first
and shared stock second.

[Browser capture](evidence/market-guidance/market.png) and
[sanitized purchase receipt](evidence/market-guidance/purchase.json) show a real
visitor banking 500 J and purchasing the first 120 J oak lot. The visitor has
380 J; another guest retains 0 J. The recipe is covered by 0.5 kg personal and
12.4 kg shared oak; predicted Make draws 0.5 kg personal then 2.0088 kg shared.
The remaining purchase goal is five lots / 2.5 kg: estimated 624 J, so bank
244 J more. Following the recipe link earns no technique.

## General recommendation and pricing contract

- Match active, unlocked goal requirements to candidate geometry using the
  same capability predicate as AI actions. Goal ids and product names do not
  choose a recipe. Saved designs participate alongside built-in designs.
- Among compatible alternatives, prefer a complete affordable plan, then
  the lowest complete cost. A cheap unrelated object or one convenient wire
  gap in an expensive machine cannot displace a compatible next capability.
  If no recipe matches the active goals, a ready optional build is labelled
  as such; it is not presented as a skill unlock.
- Price every whole lot needed, with the same scarcity curve used by actual
  buying. Later lots can cost more than the first quote. Stock is finite.
- Missing suppliers or insufficient stock produce **Stock missing**, never
  a total that prices only the available lines. Available quantities and
  partial costs remain in the plan receipt. No future replenishment is assumed.
- These are stock estimates, not reservations. Other purchases and restocks
  can change them. Buy rechecks its quote transactionally; native Make still
  checks final mass, resources and placement. No fabrication charge is added.
- Recipe line quantities retain BOM/rack precision in the API. Formatting
  stays in the UI; subgram shortfalls are not rounded to zero before planning.
  The existing stock admission tolerance is unchanged.

## Verification scope

Windows 11, Python 3.13.5, MSVC Release native runner `f819e81`; no native
physics changes. Seven Market tests are registered as `banjo_market_tests` in
CTest. They cover a four-substance plan with covered wire and missing oak,
glass and copper; actual sequential SQL purchase costs; shortages; absent
suppliers; an affordable saved goal-compatible surface over a huge build;
subgram gaps; authenticated guest scope; existing debit/retry/restock guards.

Nine Workshop tab checks pass with precise recipe quantities. The native
named-world Market check passes banking, quote changes, personal purchases,
other-guest isolation and restart. Chrome passes the real bank/purchase/plan
refresh/recipe navigation journey with no runtime exception or navigation
award. World-resolved missing equipment/intake guidance also passes. CMake
registration, Python compile, JavaScript syntax and whitespace checks pass.

The reference controller still completes both declared goal chains on both
supported generated terrains after the guidance change: 34 decisions / 60.059 s
wall on terrain 7; 35 decisions / 62.888 s wall on terrain 4. Both learn
Gathering by hand and Smelting copper. Native time remains 16.754167 / 17.204167 s
in these unattended-clock-disabled fixtures. Empty-oak-shelf fixtures on both
terrains still stop explicitly with no skill or later goal award. These are
reference acceptance checks, not live-provider or realtime-throughput results.

These tests qualify economy guidance and player isolation, not physical
manufacturing, strength, full-world conservation or distributed storage.
Remaining work includes compact product labels and next-use guidance outside
Market; continued AI play after declared checklists; live-provider seed and
shortage comparisons; generated rover delivery and world-clock timing.
