import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const code = readFileSync(
  new URL("../build/material-lab/ui/contract.js", import.meta.url),
  "utf8",
);
const { validateRecording, validateRequest, validateResult } = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`
);
// Contract-only fixture. Actual native trajectories are independently required
// by material_lab_recording_tests.py and the ordinary browser check.
const vec = () => [0, 0, 0];
function fixture() {
  return {
    schema: "banjo.material-lab-recording.v2",
    kind: "solver-recording",
    backend: "serial-double CPU Verlet",
    fp_profile: "test",
    request: { schema: "banjo.material-lab-request.v1", force_scale: 1 },
    experiments: ["load", "pull"].flatMap((interaction) =>
      ["glass", "oak", "iron"].map((material) => ({
        id: `${material}:${interaction}`,
        material,
        interaction,
        force_n: interaction === "pull" ? [0, 1e6, 0] : [10000, -20000, 30000],
        loaded_node: 72,
        dt_s: 1e-7,
        cell_m: 0.05,
        density_kg_m3: 2500,
        young_modulus_pa: 1e9,
        solver_wall_s: 1,
        load_steps: 512,
        total_steps: 640,
        bond_topology: Array.from({ length: 1261 }, () => [0, 1]),
        frames: Array.from({ length: 21 }, (_, i) => ({
          step: i * 32,
          time_s: i * 32 * 1e-7,
          phase: i <= 16 ? "loading" : "released",
          nodes: Array.from({ length: 125 }, (_, id) => ({
            id,
            position_m: vec(),
            displacement_m: vec(),
            velocity_m_s: vec(),
            mass_kg: 1,
            component: 0,
            attached: true,
            clamped: false,
          })),
          bond_state: Array.from({ length: 1261 }, () => [true, 0]),
          components: 1,
          broken_bonds: 0,
          mass_kg: 125,
          volume_m3: 0.015625,
          work_j: 0,
          kinetic_j: 0,
          elastic_j: 0,
          removed_bond_energy_j: 0,
          integration_error_j: 0,
          energy_residual_j: 0,
        })),
      })),
    ),
  };
}
test("fixed experiment contract admits its complete shape without changing it", () => {
  const f = fixture();
  assert.equal(validateRecording(f), f);
});
test("live loads and result identity must agree with the submitted request", () => {
  for (const scale of [0.25, 0.5, 1, 1.25]) {
    const f = fixture();
    f.request.force_scale = scale;
    for (const run of f.experiments)
      run.force_n = run.force_n.map((v) => v * scale);
    assert.equal(validateRecording(f), f);
    const response = {
      schema: "banjo.material-lab-result.v1",
      status: "completed",
      execution_id: "a".repeat(32),
      elapsed_wall_s: 1,
      request: f.request,
      recording: f,
      identity: {
        native_sha256: "a".repeat(64),
        request_sha256: "b".repeat(64),
        recording_sha256: "c".repeat(64),
      },
    };
    assert.equal(validateResult(response, f.request), response);
    assert.throws(() =>
      validateResult(response, { ...f.request, force_scale: 2 }),
    );
    for (const edit of [
      (r) => (r.status = "running"),
      (r) => (r.execution_id = "missing"),
      (r) => (r.identity.native_sha256 = "old"),
    ]) {
      const bad = structuredClone(response);
      edit(bad);
      assert.throws(() => validateResult(bad, f.request));
    }
  }
  for (const scale of [0, 2, true, NaN, Infinity, "1"]) {
    assert.throws(() =>
      validateRequest({
        schema: "banjo.material-lab-request.v1",
        force_scale: scale,
      }),
    );
  }
  assert.throws(() =>
    validateRequest({
      schema: "banjo.material-lab-request.v1",
      force_scale: 1,
      world: "unsafe",
    }),
  );
});
test("reject unsupported schema, duplicate experiment and incompatible input/time", () => {
  for (const edit of [
    (f) => (f.schema = "unknown"),
    (f) => (f.experiments[1] = f.experiments[0]),
    (f) => (f.experiments[0].dt_s = 0.01),
    (f) => (f.experiments[0].force_n = [0, 4, 0]),
    (f) => (f.experiments[0].frames[2].time_s = 0.01),
  ]) {
    const f = fixture();
    edit(f);
    assert.throws(() => validateRecording(f));
  }
});
test("reject corrupt cells, nonfinite metrics, missing topology and healed failure", () => {
  for (const edit of [
    (f) => f.experiments[0].frames[0].nodes.pop(),
    (f) => (f.experiments[0].frames[0].nodes[0].id = 3),
    (f) => (f.experiments[0].frames[0].work_j = NaN),
    (f) => (f.experiments[0].bond_topology[0][1] = 125),
    (f) => (f.experiments[0].frames[0].bond_state[0][0] = false),
  ]) {
    const f = fixture();
    edit(f);
    assert.throws(() => validateRecording(f));
  }
});
