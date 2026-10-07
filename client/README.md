# Replacement client: first material experiment view

This strict TypeScript client is the first isolated UI stage of the rewrite.
It shows six **recorded CPU experiments**, not a connected game world. No UI
event applies physics, inventory, wallet, AI or world mutations. See
[the checkpoint](../docs/material-lab-ui-checkpoint.md) for measured boundaries.

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
solver samples and exposes only the six named generated assets. `--generate-only`
exports the view without starting a server. Build/client/recording output stays
in ignored `build/`; `node_modules` is ignored and the compiler version is locked.
Use an existing separate native build with headless targets enabled; this target
does not require raylib or modify its interactive frame/runtime settings.

`contract.ts` validates the fixed experiment schema/units, sample times, bounds,
stable topology and non-healing failures. `lab.ts` only projects samples and
updates controls. There is no interpolation across a fracture or simulation law
in the client. Static bond topology is stored once; dynamic bond states remain
sampled. Displacement magnification and slow replay are labelled and change only
the display. A packet/binary fingerprint is not certification of a material model.

Checks:

```powershell
node --test tests/material_lab_client_tests.mjs
python tests/material_lab_recording_tests.py build/local-cell-tools/Release/banjo_material_lab_record.exe -v
ctest --test-dir build/local-cell-tools -C Release --output-on-failure -R '^banjo_material_lab_recording_tests$'
```

Next add bounded live experiment commands and actual finite contact/settling,
then reuse the validated interaction and snapshot boundaries in the
World/Inventory/Build/Progress shell. Authenticate live mutations and add durable
state before migrating the retained game. This viewer does not close those gates.
