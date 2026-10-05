# The player regression

A test suite that plays the game the way a person does and checks what a person would notice. The owner asked for it on 2026-10-04: "a regression test that we run to make sure we can dig in a spot and everything behaves as we expect, same for walking, operating the rover, going into the workshop and making changes".

That day's bugs were all things a player feels: clicks that answered late or queued up, holes that did not get deeper, being flung off the map, a pile heaped over the hole, a walk that stuttered, names that did not show on hover. Unit tests did not see any of them. This suite is built to.

## How it plays

- **A real page.** Each journey opens the world page in headless Chrome, as a new player.
- **Real input.** Keys and mouse go in through Chrome's own input (DevTools `Input.dispatchKeyEvent` and `Input.dispatchMouseEvent`), so they pass through the page's real handlers. Nothing calls the page's functions in place of a key or a click.
- **The real game.** The world is a named world on 25 cm cubes (`surface: columns`, the valley grown from seed 7), run by the real engine, with its own server on a free port.
- **As a body.** A new player starts as a body, not a flying camera, and so does the test.
- **Measured.** Each journey measures what a player would notice: how long a click takes to answer, how far a hole went down, how fast the body walks and whether it stutters. When something is wrong, the failure says so in plain words, with the numbers.

Each journey checks everything it can before failing, so one run lists every problem it found, not only the first.

## The journeys

### 1. Dig in one spot (`test_dig_in_one_spot`)

The player looks at the field pick and presses E to take it up. They press Q to put it in the bag. The test then moves them to a spot with deep soil on three sides, and they take the pick back out by clicking it in the inventory strip.

Facing east, then south, then north, they aim at one cube about 2 m away. With the mouse held still in the middle of the view, they click six times, 250 ms apart. For each hole it checks that:
- every click is answered within 400 ms, timed from the mouse press to the server's reply;
- clicks do not queue: at most one dig is in flight at a time, and the burst is over within 1.5 s of the last click;
- no click lands on a pile and collects it by mistake;
- the first top click lowers its column one cube (0.25 m); later receipts match their actual clicked points, including walls exposed by the first cut;
- columns that were never clicked do not change;
- the hole is drawn at the depth the engine has it;
- everything dug ends up in piles, kilogram for kilogram.

When all three holes are dug, it checks that:
- no pile sits within 1 m of any hole;
- the page shows the piles;
- the player is still standing upright, on the ground, within 0.3 m of where they started.

It digs facing more than one way because, until 2026-10-04, the way you faced decided which cube a click took. Facing east or south, the hole grew away from you instead of getting deeper.

### 2. Walk (`test_walk`)

The player faces the most level, dry direction near where they start. They hold W for 2 s, then S, then A, then D. The test records where the eye is on every frame and works out the speed over each tenth of a second. For each key it checks that:
- the body gets to 90% of its steady speed within 0.4 s;
- while the key is held, the speed never drops below 70% of steady speed for more than 0.2 s at a time (no stutter);
- the body stops within 0.5 s of the key coming up;
- no walk request fails or takes longer than half a second.

Then it checks that:
- Space jumps at least 0.5 m and comes back down onto the ground;
- the body climbs a 25 cm step. The test digs a pit one cube deep around the player and walks them out of it.
- the body never leaves the map, never ends up under the ground and never ends up tipped over.

### 3. Operate the rover (`test_operate_the_rover`)

The player clicks the rover. Its panel must open within 1 s. They close it, then get into the rover from Menu → Drive a machine. They hold W for 4 s, and the rover must move more than 0.5 m. Three seconds after letting go, it must move less than 0.5 m in one second.

### 4. The Workshop: change a design and make it (`test_workshop_change_and_make`)

The player clicks Recipes on the world's bottom bar, then "Open in Lab" on the Camp stool. They type "make the legs thicker" into the Lab's chat and press Enter. The legs must get heavier.

They then make the stool the paid way, with real supplies and energy: Make, Prepare supplies, Start make, Run, and Add to Inventory. Back in the world, the stool must be in the inventory strip with a picture, and clicking it there must put it in the player's hand.

### 5. Point and click (`test_point_and_click`)

Hovering over the solar farm, the camp light and the rover must show each one's name within 0.5 s. Clicking the rover or the solar farm must bring a card about it onto the screen within 1 s, and the game must not refuse the click. With the pick in hand, clicking the rover must open its panel, not swing the pick.

## What it leaves behind

Each journey writes two files to `build/player-regression/`:
- `<journey>.json` has the numbers it measured, the steps it took and every problem it found. It also lists every request the server took more than a quarter of a second to answer. A stall a player feels usually shows up there.
- `<journey>.png` is a picture of the page as the journey ended.

## How to run it

The runner finds the engine for you and prints what each journey found at the end:

```
python tools/player_regression.py --build C:/cs/build/w/Release
python tools/player_regression.py --build C:/cs/build/w/Release dig walk    # only these journeys
```

To run the suite directly instead:

```
BANJO_LIVE_ENGINE=<build>/banjo_live_world_run.exe python tests/player_regression_tests.py -v
```

You need:
- the engine: `banjo_live_world_run`, with `banjo_platform_cli` in the same folder;
- Chrome: set `BANJO_CHROME` if it is not installed in Chrome's usual Windows location.

Without these, the suite is skipped. If `BANJO_BROWSER_TESTS=required` is set, as CI and the runner set it, the suite fails instead.

Each journey starts a server of its own on a free port, inside the test process. It never touches anybody else's server.

CI runs the suite at the end of the "Test playground HTTP boundary without an API key" step in `.github/workflows/ci.yml`. It is not registered with ctest, the same as the other browser suites.

## How long it takes

About 4 to 5 minutes for all five journeys on the owner's machine, one after another:

| Journey | Time |
|---|---|
| Dig | about 40 s |
| Walk | about 45 s |
| Rover | about 25 s |
| Workshop | about 35 to 50 s |
| Point and click | about 25 s |

Each journey also spends about 10 to 20 s opening its world and waiting for it to settle.

## Reading a failure

- **Run it on a quiet machine.** The journeys measure time. A server short of processor time feels slow for reasons of its own. A failure under load is not a finding until it fails again with the machine quiet.
- **Look at `server_slow_requests` in the journey's JSON.** When a walk or a click was late, the request that was holding the world up at that moment is usually listed there.
- **Walk timings are measured to the nearest frame.** CI draws in software at a few frames a second, so the walking limits there allow one extra frame.
