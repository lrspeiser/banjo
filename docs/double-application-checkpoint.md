# Double-position application promotion

Local source `d96ca7e303ad195452de25b36c66db97a5ef2c3a`, September 5, 2026; not pushed or merged. The full platform goal remains active.

New runtime builds now default to Jolt `DOUBLE_PRECISION=ON`. An explicit/cached OFF remains OFF for compatibility and regression, so reconfiguring an existing legacy build does not silently reinterpret its worlds. A fresh headless configure with no precision argument selected ON; the separate graphical build explicitly uses ON. This changes position storage, not Jolt's float velocities or all other numerical quantities.

## Active application and recovery locations

The graphical binaries are in `C:/Users/henry/dev/banjo-integration/build/win-joint-double/Release`. Both `banjo_starter.exe` and `banjo_workshop.exe` are running with converted copies:

- Starter: `build/starter-double-play`, save `starter-world.json`.
- Workshop: `build/workshop-double-play`, save `world.json`.

The original applications were closed normally before copying their latest state. Original workspaces `build/starter-play` and `build/assembly-review-ui-play` remain unchanged after conversion. Each new workspace retains `source-save.json`, `normalized-32.json` and `conversion-package.json`; assembly input/test files were copied where present. The package was generated through the validated converter, not by manually changing a signature. Source SHA-256 checks still match after native verification. The old single-position build remains available, as does the unrelated original laboratory window, which was not touched.

To reopen the new applications, run the double-position binaries with `--workspace build/starter-double-play` or `--workspace build/workshop-double-play --view assembly`, from the integration repository. A save from either new workspace must not be opened by the old single-position binary; version-5 identity checks reject that mismatch.

## Verification

Full graphical Release build and all 25 CTest suites pass in 19.69 s, including the glass/oak/iron runtime cohesive precision accuracy gate, persistence and conversion suites. Fresh-default configuration verified ON. Custom frame control, busy wait and static MSVC runtime remain OFF. Windows 11 / MSVC 19.44 x64 Release / CMake 4.1.2 / Jolt 5.6 / raylib 6 / Core Ultra 9 285K / RTX 5090 / OpenGL 3.3.

Normal Windows input/render checks used the actual double-position processes, not capture-only mode:

- Starter clearing renders without player body parts. Tab opens the three-material inventory, and the mouse Back to World button returns to the scene.
- Normal close saves 64-bit identity; restart loads it. Saved ticks advanced by 46,191 in the measured first native session, while inventory, XP, stamina, receipts and remembered design/assembly values remained unchanged. This proves a running clock for that session, not precise real-time pacing or full gameplay correctness.
- Restart with the existing `--layout crafting` fixture puts the camera at the table for control verification. Native clicks select glass/oak/iron ball designs: shortages display 0.670/0.188/2.110 kg respectively with empty stock; iron retains its level-2 and 14-stamina requirement. Glass/oak show level 1 and 10 stamina. The fixture does not prove walking to or aiming at the table.
- Workshop restores oak assembly revision 1, 0.0245 kg required and 10 kg held. Native test controls load the saved specification, run the isolated separation test and export exact-revision evidence. The result is 100% separation with signed energy residual -4.4650925179468e-9 J and accumulated error about 7.97221e-9 J. This is the existing isolated CPU assembly test, not a live in-world joint.
- Normal workshop close/restart preserves its full paused-world JSON, including 64-bit signature, stock and assembly declaration. Test results are not auto-restored as current claims. An application-generated F12 image and exported test report are retained as evidence.

No real LLM request, full walking/gathering/crafting/cutting sequence, live joint, force-law change or new material calibration is claimed here. The single-position failure evidence remains retained; the promoted configuration passes only the stated bounded cases. Float velocity accumulation, nonmonotonic endpoint errors and general trajectory/spatial convergence remain open.

Next connect finite-area joint forces to runtime motion with complete surface contact, work/reaction accounting and bounded failed-step handling. Continue physical fabrication energy, realistic branch cutting and all remaining platform gates. All 40 mechanics/platform scorecard rows remain retained.
