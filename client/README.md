# Replacement client: first material experiment view

This strict TypeScript client is the first isolated UI stage of the rewrite.
It loads a six-case CPU baseline and now supports **fresh bounded experiments**.
Choose Load strength, click Run experiment, then play/scrub the returned samples.
It is not a connected game world and cannot change player stock, wallets or AI.
See [the live checkpoint](../docs/material-lab-live-checkpoint.md) and
[the baseline checkpoint](../docs/material-lab-ui-checkpoint.md) for boundaries.

With Node 22 and the existing Windows native Release build:

```powershell
cd client
npm ci --ignore-scripts
npm run check
npm run build
cd ..
cmake --build build/local-cell-tools --config Release --target banjo_material_lab_record --parallel 4
python scripts/material-lab.py --native build/local-cell-tools/Release/banjo_material_lab_record.exe
```

Open `http://127.0.0.1:18891/`. The launcher binds loopback, generates actual
solver samples and exposes six named assets plus a same-origin bounded experiment
endpoint. There is one execution slot and no automatic solver/model polling.
`--generate-only`
exports the view without starting a server. Build/client/recording output stays
in ignored `build/`; `node_modules` is ignored and the compiler version is locked.
Use an existing separate native build with headless targets enabled; this target
does not require raylib or modify its interactive frame/runtime settings.

`contract.ts` validates the v2 recording, v1 request/result, sample times, bounds,
stable topology, matching load and non-healing failures. Refused runs retain the
previous result. `lab.ts` sends a deliberate command and projects exact samples.
There is no interpolation across a fracture or simulation law
in the client. Static bond topology is stored once; dynamic bond states remain
sampled. Displacement magnification and slow replay are labelled and change only
the display. A packet/binary fingerprint is not certification of a material model.

Checks:

```powershell
node --test tests/material_lab_client_tests.mjs
python tests/material_lab_recording_tests.py build/local-cell-tools/Release/banjo_material_lab_record.exe -v
ctest --test-dir build/local-cell-tools -C Release --output-on-failure -R '^banjo_material_lab_recording_tests$'
```

Next qualify actual finite contact/settling and a shared compiler/job gateway,
then reuse the validated interaction and snapshot boundaries in the
World/Inventory/Build/Progress shell. Authenticate live mutations and add durable
state before migrating the retained game. This viewer does not close those gates.
