# Expedition gameplay checkpoint

Implemented September 19, 2026, as a bounded personal-world prototype.
Open **/world?scene=expedition** or choose **Expedition · gather and build**.
The existing sandbox remains available as **world**.

## The first loop

Walk with W A S D and look with the mouse. Escape releases the pointer so the
side panel can be used. The gold marker is the drying camp; pale markers are
loose stone, amber markers are dry branches, and teal markers are wet timber.
Gather within 2.5 m. The material pack holds 20 kg and is distinct from the
sandbox's inventory of whole native bodies.

Gather 2 kg stone, 1 kg dry branches and 1 kg wet timber. At the camp, build
the dryer (2 kg stone and 0.5 kg wood), load 1 kg wet timber, add 0.2 kg fuel,
and light it. Fuel first heats the charge, then supplies its latent heat.
The wet stock contains 0.8 kg dry wood and 0.2 kg water per kilogram. Drying
leaves 0.8 kg timber; water leaves as accounted vapor. Let it cool below
60 C, then collect it. The resulting dry timber can fuel a later batch.

The firebox holds 0.5 kg, output occupies the dryer until collected, and a
full material pack cannot receive output. Empty fuel leaves unfinished work.
Extinguishing does not return consumed fuel or erase heat. A thermostat stops
burning when no wet charge remains, retaining unused fuel.

## Sources, geography and progression

The native TerrainGenerator creates the valley's landforms, drainage channel,
erosion and flowing water, using its existing deterministic seed 7 and cache.
The gameplay planner reads that actual heightfield and chooses a connected
upper terrace with gentle slopes, excluding the native water mask. Six finite surface-stock sites lie on that
connected ground, close to the camp. The planner checks reachable area,
hand-gatherable construction materials, wet stock and finite dry fuel.
An unusable terrace is refused; unrelated mineral patches are not injected
to repair it. This first scene has one seed; arbitrary world selection and
automatic seed retry are future work.

These stocks are an explicit initial endowment of **loose surface material**.
They are additional to the engine's soil/rock columns: gathering does not
pretend to mine those columns or cut a living tree. Geological ore deposits,
biomes, vegetation growth, geological processing chains and regional resource
scarcity remain to implement. The existing terrain generator supplies the
plausible land; this checkpoint supplies only the first progression test.

Fuel starts with finite chemical energy. The dryer consumes dry wood under a
declared 16 MJ/kg demonstration law. Batteries, renewable harvesting,
player stamina, food and hydraulic power do not gain new capabilities here.
Player stamina remains a separate gameplay unit in the older starter loop.

## Clock and persistence

The native accepted elapsed time is authoritative. The browser requests
ordinary engine steps with a realtime target; load can make simulation slower
than wall time. No extra production is credited for wall time the engine did
not accept. The 30-minute sunlight cycle changes presentation, not the duration
used for chemistry, water, mechanics or machines.

Pause, hidden tabs and closed personal-world pages stop requesting steps.
No offline catch-up runs. Waiting uses the same native step route, in
one-second chunks; the browser's wait control advances at most 30 seconds and
can stop between chunks. Native water and rigid bodies advance too. There is
no isolated timer that awards completed output.

The native snapshot and gameplay state are written in the same atomic room
file. Acknowledged gameplay actions are saved before success. Periodic native
autosaves retain intervening elapsed simulation; a hard crash can lose time
since the last autosave. Scene switching and reopening retain both states.
A missing half, edited scene, unreadable expedition save, clock reversal, or
incomplete native restoration refuses to start rather than replenishing stocks.
The existing sandbox's recovery behavior is unchanged.

The saved gameplay state includes each depleted surface stock, material and
sensible heat in the pack, construction material, fuel, water, wood, stored
heat, damage, ignition state, clock and action receipts. Matching retries do
not repeat inventory transfers. Personal-world coordinates are supplied by
the client; this is not a multiplayer anti-cheat boundary.

## Declared process model and limits

This is a small Python operating model attached to native time, **not** a new
native thermochemical solver. Existing native combustion/drying remains
separate and unchanged. The prototype uses:

| Parameter | Value and meaning |
|---|---|
| Fuel power | 4,000 W chemical, limited by remaining dry fuel |
| Useful fraction | 0.65 to the dryer; remaining heat to ambient |
| Lump heat capacity | 4,000 J/K plus wood at 1,500 J/kg/K and water at 4,180 J/kg/K |
| Heat loss | 8 W/K to a prescribed 293.15 K environment |
| Boiling | 373.15 K, latent heat 2.257 MJ/kg |
| Oxygen | 1.184 kg ambient oxygen per kg fuel; products leave at 2.184 kg/kg |
| Thermal integration | explicit steps at most 0.25 s; no dropped elapsed interval |
| Overheat history | damage increases above 453.15 K; default thermostat prevents this regime |

The ignition spark is neglected; all macroscopic heating comes from finite
fuel. Composition and combustion exhaust are aggregate inventories. Vapor
carries latent and sensible heat. Collected timber retains sensible heat in
the material pack, which is treated as adiabatic in this version. Construction
materials remain in the audit. Gathering and assembling are gameplay
operations; manufacturing work and tool wear are not yet energy-accounted.

The report separately closes material mass (including ambient oxygen and
outgoing vapor/products) and the dryer energy ledger (released chemical heat,
stored sensible heat, vapor enthalpy, ambient transfer). Small local residuals
do not establish whole-world energy conservation. Exhaust and heat go to the
declared infinite environment; they do not heat nearby native objects or a
finite room atmosphere. The camp and stocks have visible location markers,
not native collision or fracture geometry. There is no general product
manufacturing, melting/casting, machinery damage qualification or distant
simulation reduction in this checkpoint.

## Python, HTTP and MCP contract

Pure host functions live in mcp/gameplay.py:

- new(terrain, time_s=0, seed=7, water=None): plan stocks from the native packed heightfield.
- advance(state, time_s): advance to accepted absolute native seconds.
- action(state, request): return an atomic candidate; never mutate the source.
- report(state): return clock, contents, conditions and local audit.

The browser host owns persistence and session checks. JSON numbers must be
finite. Weights are kg, positions are [x,y,z] metres, temperatures K, heat J,
and native time seconds.

| HTTP operation | Request / result |
|---|---|
| POST /api/world/open | {"scene":"expedition"} returns session plus gameplay; rejoining renews session ownership. fresh is refused. |
| POST /api/world/gameplay | {"session":"…","op":"state"} reads gameplay without advancing. |
| POST /api/world/gameplay | {"session":"…","op":"action","action":{…}} validates and durably commits a gameplay action. |
| POST /api/live/act | {"session":"…","op":"step","dt":0.008333333333333333,"n":120} advances one native second and returns gameplay alongside native state. |

State-changing requests require X-Banjo-Token from GET /api/status, as for
the existing browser APIs. Stale sessions and invalid actions return errors.
Sandbox authoring and unbounded heating are unavailable inside this expedition.

Every action contains action, request_id (1–80 characters) and at_m.
Optional node names a surface stock and kg chooses the transferred amount:

| action | Parameters and limits |
|---|---|
| gather | node, kg default 1, range 0.01–2; one world second between gathers |
| build | consumes 2 kg stone and 0.5 kg dry_wood |
| load | kg default 1, range 0.01–2 wet_wood; dryer must be empty |
| fuel | kg default 0.2, range 0.001–0.5 dry_wood, 0.5 kg total firebox |
| light | needs fuel, wet charge and damage below 1 |
| extinguish | closes fuel feed, preserving material and heat |
| collect | transfers all dry wood when below 333.15 K and pack has space |

Use the same request_id and identical request when retrying a lost response.
Reusing it with another payload refuses. Receipts are retained in this small
prototype; bounded receipt compaction is future work.

Both MCP servers version **1.3.0** expose expedition_open, expedition_state,
expedition_action and expedition_wait. They forward to the same local browser
world. Set BANJO_PLAYGROUND_URL to a loopback HTTP origin (default
http://127.0.0.1:8765); start the playground first. They cannot target hosted
password-protected servers or the MCP authoring copy.

expedition_open has no arguments and returns session and gameplay.
expedition_state takes session. expedition_action takes session and the
action object above. expedition_wait takes session and integer seconds 1–30.
Pause browser stepping before an MCP wait if exact requested elapsed time
matters. Waiting is not retry-idempotent: after a connection error read the
clock before requesting more time. All transfers are still driven by the
accepted native clock. Existing C/Python ABI remains **25**; no fictitious
native gameplay entry points are advertised.

## Verification

tests/gameplay_tests.py covers deterministic/invalid terrain, complete drying,
fuel exhaustion, retained heat, partial save/resume, no offline credit, clock
reversal, finite inputs, reach, atomic refusals, duplicate receipts, damage
persistence and failed-save rollback. tests/gameplay_live_tests.py runs the
native valley through HTTP, switches scenes, restarts the server, completes
and collects a batch, and checks both MCP distributions against that state.

This is bounded gameplay/process evidence, not fresh full-engine or general
glass/oak/iron material qualification. The next checkpoint should replace
surface markers with installed construction geometry, add geology-based
resource placement, and connect the process to native thermal/material ports.

Measured final run: all four registered gameplay/API/MCP CTest suites passed in
216.4 seconds, including 68 legacy MCP cases. The native expedition integration
completed in 53.3 seconds. Its batch audit residuals were below 2e-14 kg and
4.3e-9 J after 1,438 native seconds. Browser gathering, reload and 30-second
waiting were exercised with no browser errors.
