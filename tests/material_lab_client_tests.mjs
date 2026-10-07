import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const code = readFileSync(
  new URL("../build/material-lab/ui/contract.js", import.meta.url),
  "utf8",
);
const { validateRecording } = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`
);
// Contract-only fixture. Actual native trajectories are independently required
// by material_lab_recording_tests.py and the ordinary browser check.
const vec = () => [0, 0, 0];
function fixture() {
  return {
    schema: "banjo.material-lab-recording.v1",
    kind: "solver-recording",
    backend: "serial-double CPU Verlet",
    fp_profile: "test",
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
