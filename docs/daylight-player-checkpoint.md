# Player day/night checkpoint — October 1, 2026

Implementation publication is recorded below after the verified checkpoint push.
This completes player-experience item 2 within its declared rendering/native
energy boundary. The full fourteen-item goal remains active.

## What the player sees

New worlds retain the native 600 s day. A small sun disc and halo follow the
native `sun.toward` direction, disappear below the horizon and can be obscured
by nearer terrain. The existing directional shadow follows that same direction.
Night ambient/rim/fill lighting is lower, so the battery-powered camp lamp
visibly lights the nearby ground while distant hills remain dark.

Selecting the solar array, its components, a program's battery or the wired
camp lamp shows actual charge/capacity, a battery fill indicator and energy
flow. Incoming/outgoing watts are measured from native cumulative `taken_j` /
`given_j` divided by native elapsed time. This includes lamps and process loads,
which the former motor-only display omitted. The former non-program display
always claimed nothing was flowing. First/reset readings now say they await
the next reading; duplicate timestamps preserve the preceding measured rate.
Changing worlds clears previous samples. These stores are physical energy;
the personal Market wallet is a separate existing account.

## Verification

Windows 11, Python 3.13, installed Chrome at 1280 × 800, MSVC Release native
runner from the preceding `a64c1e5` checkpoint. Native sources/laws are unchanged.

`tests/world_daylight_tests.py`, registered as `banjo_world_daylight_tests`,
passes both the retained native cycle experiment and the new full browser
journey. CTest Release: 2 cases pass in 10.68 s (10.70 s total).

The native accelerated experiment declares a 10 s day, uses the existing
native step path and verifies actual solar input, lamp night/dawn switching,
20 W lamp draw and 100 J consumed during its five-second night. The native
charge accounting tolerance remains `3e-5 J`; lamp draw tolerance `1e-5 J`.
Production remains a 600 s day. No conservation tolerance was relaxed.

The browser opens an ordinary generated world through HTTP, advances its
native simulation and reads returned native sun/store/lamp state. Explicit
morning/noon/night sun settings isolate visual comparisons; the separate
continuous native cycle verifies the actual progression through night/dawn.

| Observation | Morning | Noon | Night |
|---|---:|---:|---:|
| GPU mean luminance, 0–255 | 134.6 | 167.6 | 11.5 |
| Selected store net flow | +221.90 W | +535.14 W | −20.00 W |
| Native store charge | 1,990,142.83484 J | 1,990,484.01049 J | 1,990,471.67716 J |
| Native lamp | Off | Off | Lit, 2,400 lm |

The solar charge rises in the actual native store; displayed joules match the
returned values exactly. Night flow is measured at −19.9998 W (wire counter
precision), within the unchanged native 20 W declaration. Selecting the camp
lamp displays its supplying store and the same outgoing flow. Dawn switches
the lamp off and returns positive incoming solar energy.

At a fixed ground camera, comparing GPU pixels with the directional shadow
enabled/disabled detects 16,852 / 12,168 affected pixels at morning/noon. Their
centroids move 47.97 pixels. The diagnostic restores the light before returning
and changes no native state. Looking toward the native sun renders a bright
disc at its projected position; the disc is absent below the horizon.

Physically unwiring the native lamp at night lowers the same view's mean
luminance from 11.5 to 7.8. Rewiring it preserves its native energy source.
Zero browser exceptions are recorded. Screenshots were inspected for the
visible sun, night lamp pool and readable charge/flow values.

Ignored reproducible artifacts: `build/resource-flow/daylight-verified.json`,
`daylight-verified-{morning,noon,night,sun,unwired}.png` and the affected player
suite log. Run:

```sh
ctest --test-dir build/agent-progression -C Release -R '^banjo_world_daylight_tests$' --output-on-failure
```

The existing 15-case resource/player/browser suite also passes in 104.115 s.
Source registration remains 286/286, with
no deliberate exclusions.

## Boundaries and next work

Sun size/halo, twilight, underground dimming, ambient levels and lumen-to-point
light intensity remain presentation approximations. They are not calibrated
photometry, a thermal model or a new material law. No glass/oak/iron constitutive
claim is added. Shadow qualification covers this ordinary scene/camera and the
existing local shadow map; it is not cross-GPU determinism or an unlimited
range shadow certificate. Explicit saved worlds retain their declared sun,
including static lighting. Network flow readings average the most recent
native interval; they do not promise future generation or consumption.

Verified player items are now 2, 3, 6 and 9. Nine other items remain partial;
item 11 durability/repair remains pending. Next finish recipe shortage routes
and the tool/full/empty journey, then mixed-material pick admission, native
damage/repair, reacting avatars and cargo/tipping with measured acceptance.
