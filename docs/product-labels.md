# Product names, ownership and next use — September 30, 2026

## Player view

Inventory shows a product picture, **Camp stool**, **2.51 kg**, its bag/hand,
**Owner: You**, **Next use: Hold / place in World**, and **Open in Lab**.
Native item/body/design ids, exact mass and its source live in folded Details.
The World bag and inspection panel use the same recorded product name.

Resource cards show a readable total plus separate **Personal** and **Shared**
quantities. For example, the 0.4912 kg remainder reads **491.2 g**; 12.4 kg
is not rounded to 12 kg. Click a resource to find Recipes that use it;
**All materials** restores the full catalog. Recipe details show predicted
personal/shared debits, while the card states **Make uses: Personal → Shared**.
These are predictions from current stock; Make still checks and debits stock.

[Inventory capture](evidence/product-labels/inventory.png) and
[World bag capture](evidence/product-labels/world-bag.png) show actual Chrome
interactions. Source pictures show the recorded design, not the current damaged
body or a functional certification. Opening and clearing the Lab leaves the
carried item's native state and ownership record unchanged.

## Source and mass contract

`playground/product_labels.py` centralizes named sources for Recipes and built
products. Matching uses normalized kind, parameters and component overrides.
A client-chosen design id cannot name a different geometry Camp stool or borrow
a saved design's name. Built-in named sources and saved sources use the same
normalization. Other variants retain a readable assembly-kind name.

New installs freeze their display label in the existing installation receipt
at preview, then persist it with commit. Renaming a saved design later does not
rename an already-built product. Legacy receipts resolve their recorded source;
unrecognized legacy products say Built item. Native ids remain action keys.
Presentation metadata grants no ownership, skill, physics admission or goal.

Pose replies omit packed bodies. Inventory uses a live native mass when present;
otherwise a packed item can show the saved native checkpoint's parked mass.
**Every native part must have a saved mass** before a whole-item value is shown.
Details names that source and saved time. Missing values read Mass unavailable,
never zero or an estimated recipe mass. Exact native quantities remain in the API.

Next-use labels come from implemented actions. Only an actual swing-and-lever
tool profile advertises Study / gather in World. A design's purpose or display
name cannot claim that an unsupported machine works.

## Verification

Source: outgoing working tree based on main `3567c57`; publication is recorded
in the follow-up below. Windows 11, Python 3.13.5, MSVC Release CPU native runner
`f819e81`, unchanged `1/240 s` step and 50 mm scene cells. No C++ changes.

- Five `banjo_product_labels_tests` cases cover normalized source matching,
  a wrong geometry with the same design id, persisted frozen saved names,
  unknown legacy receipts, actual tool next use and incomplete saved mass.
- Nine Workshop-tab and sixteen native Inventory-room checks pass.
- A real two-guest paid Camp run preserves all existing native body records
  byte for byte and both player records while another bench is admitted.
  Each packed stool reads 2.5088 kg, and both names/bags survive server restart.
  [Sanitized checkpoint receipt](evidence/product-labels/acceptance.json)
  includes matching body digests without guest tokens.
- Chrome passes resource filtering/All materials; carried source preview,
  folded Details, mass and unchanged Lab selection; and the paid Goals →
  Market → Recipes → World packing journey with the same World bag name.
  An initial concurrent browser run did not initialize in 30 s; the isolated
  rerun reached packing and exposed title-case drift, which was fixed. Both
  affected isolated browser journeys subsequently passed.
- Reference AI completes all eight Camp/Workshop goals on two generated maps,
  retaining its own possessions and two techniques. Terrain 7: 34 decisions,
  60.086 s wall / 16.804167 s native; terrain 4: 35 decisions, 62.370 s wall /
  17.154167 s native. These fixtures disable the unattended clock and include
  planning/request time. They do not measure realtime simulation throughput.

This qualifies presentation and retained player state, not new constitutive
physics, structural strength, material realism, conservation closure or server
capacity. Earlier glass/oak/iron comparative gates remain unchanged.

## Remaining playtest work

The reference controller stops after the declared checklists at **2/10**
techniques. Continued play, exhausted machine intake replenishment, generated
rover delivery and AI/page/background clock ownership remain open. No local
provider key is configured; zero live-provider calls were made. The separate
[AI explorer review](ai-explorer-checkpoint.md) retains the original persistent
run, watch link, measured results and limitations.
