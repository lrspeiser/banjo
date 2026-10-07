export type Vec = [number, number, number];
export type Cell = {
  id: number;
  position_m: Vec;
  displacement_m: Vec;
  velocity_m_s: Vec;
  mass_kg: number;
  component: number;
  attached: boolean;
  clamped: boolean;
};
export type Frame = {
  step: number;
  time_s: number;
  phase: string;
  nodes: Cell[];
  bond_state: [boolean, number][];
  components: number;
  mass_kg: number;
  volume_m3: number;
  work_j: number;
  kinetic_j: number;
  elastic_j: number;
  removed_bond_energy_j: number;
  integration_error_j: number;
  energy_residual_j: number;
  broken_bonds: number;
};
export type Run = {
  id: string;
  material: string;
  interaction: string;
  force_n: Vec;
  loaded_node: number;
  dt_s: number;
  cell_m: number;
  density_kg_m3: number;
  young_modulus_pa: number;
  solver_wall_s: number;
  bond_topology: [number, number][];
  frames: Frame[];
};
export type Recording = {
  schema: string;
  kind: string;
  backend: string;
  fp_profile: string;
  request: ExperimentRequest;
  experiments: Run[];
};
export type ExperimentRequest = {
  schema: "banjo.material-lab-request.v1";
  force_scale: number;
};
export type ExperimentResult = {
  schema: "banjo.material-lab-result.v1";
  status: "completed";
  execution_id: string;
  elapsed_wall_s: number;
  request: ExperimentRequest;
  identity: {
    native_sha256: string;
    request_sha256: string;
    recording_sha256: string;
  };
  recording: Recording;
};
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const object = (v: unknown): Record<string, unknown> => {
  if (typeof v !== "object" || v === null || Array.isArray(v))
    throw new Error("Invalid recording object");
  return v as Record<string, unknown>;
};
const vec = (v: unknown): v is Vec =>
  Array.isArray(v) && v.length === 3 && v.every(finite);
export function validateRequest(value: unknown): ExperimentRequest {
  const request = object(value);
  if (
    Object.keys(request).length !== 2 ||
    request.schema !== "banjo.material-lab-request.v1" ||
    !finite(request.force_scale) ||
    ![0.25, 0.5, 1, 1.25].includes(request.force_scale)
  )
    throw new Error("Unsupported experiment load");
  return value as ExperimentRequest;
}
export function validateRecording(value: unknown): Recording {
  const root = object(value);
  const request = validateRequest(root.request);
  if (
    root.schema !== "banjo.material-lab-recording.v2" ||
    root.kind !== "solver-recording" ||
    root.backend !== "serial-double CPU Verlet" ||
    typeof root.fp_profile !== "string" ||
    !Array.isArray(root.experiments) ||
    root.experiments.length !== 6
  )
    throw new Error("Unsupported material recording");
  const ids = new Set<string>();
  for (const raw of root.experiments) {
    const run = object(raw);
    if (
      typeof run.id !== "string" ||
      ids.has(run.id) ||
      !["glass", "oak", "iron"].includes(String(run.material)) ||
      !["load", "pull"].includes(String(run.interaction)) ||
      run.id !== `${run.material}:${run.interaction}` ||
      !vec(run.force_n) ||
      run.loaded_node !== 72 ||
      run.dt_s !== 1e-7 ||
      run.cell_m !== 0.05 ||
      !finite(run.density_kg_m3) ||
      run.density_kg_m3 <= 0 ||
      !finite(run.young_modulus_pa) ||
      run.young_modulus_pa <= 0 ||
      !finite(run.solver_wall_s) ||
      run.solver_wall_s < 0 ||
      run.load_steps !== 512 ||
      run.total_steps !== 640 ||
      !Array.isArray(run.frames) ||
      run.frames.length !== 21
    )
      throw new Error("Invalid matched experiment");
    const expectedForce =
      run.interaction === "pull" ? [0, 1e6, 0] : [10000, -20000, 30000];
    if (
      !run.force_n.every(
        (v, i) => v === (expectedForce[i] ?? NaN) * request.force_scale,
      )
    )
      throw new Error("Unexpected laboratory force");
    if (!Array.isArray(run.bond_topology) || run.bond_topology.length !== 1261)
      throw new Error("Incomplete bond topology");
    for (const pair of run.bond_topology)
      if (
        !Array.isArray(pair) ||
        pair.length !== 2 ||
        pair[0] === pair[1] ||
        !pair.every((v) => Number.isInteger(v) && v >= 0 && v < 125)
      )
        throw new Error("Invalid bond topology");
    ids.add(run.id);
    for (let i = 0; i < run.frames.length; i++) {
      const frame = object(run.frames[i]);
      if (
        frame.step !== i * 32 ||
        !finite(frame.time_s) ||
        Math.abs(frame.time_s - i * 32 * run.dt_s) > 1e-15 ||
        !Array.isArray(frame.nodes) ||
        frame.nodes.length !== 125 ||
        !Array.isArray(frame.bond_state) ||
        frame.bond_state.length !== 1261 ||
        !Number.isInteger(frame.components) ||
        Number(frame.components) < 1 ||
        Number(frame.components) > 125 ||
        !Number.isInteger(frame.broken_bonds) ||
        frame.phase !== (i <= 16 ? "loading" : "released")
      )
        throw new Error("Invalid recorded frame");
      for (const key of [
        "mass_kg",
        "volume_m3",
        "work_j",
        "kinetic_j",
        "elastic_j",
        "removed_bond_energy_j",
        "integration_error_j",
        "energy_residual_j",
      ])
        if (!finite(frame[key])) throw new Error(`Invalid measured ${key}`);
      for (let nodeId = 0; nodeId < 125; nodeId++) {
        const node = object(frame.nodes[nodeId]);
        if (
          node.id !== nodeId ||
          !vec(node.position_m) ||
          !vec(node.displacement_m) ||
          !vec(node.velocity_m_s) ||
          !finite(node.mass_kg) ||
          node.mass_kg <= 0 ||
          !Number.isInteger(node.component) ||
          Number(node.component) < 0 ||
          Number(node.component) >= 125 ||
          typeof node.attached !== "boolean" ||
          typeof node.clamped !== "boolean" ||
          ![
            ...node.position_m,
            ...node.displacement_m,
            ...node.velocity_m_s,
          ].every((v) => Math.abs(v) < 1e9)
        )
          throw new Error("Invalid cell state");
      }
      for (let b = 0; b < frame.bond_state.length; b++) {
        const bond = frame.bond_state[b];
        if (
          !Array.isArray(bond) ||
          bond.length !== 2 ||
          typeof bond[0] !== "boolean" ||
          !finite(bond[1]) ||
          bond[1] < 0 ||
          bond[1] > 1
        )
          throw new Error("Invalid bond state");
        if (i > 0) {
          const previous = object(run.frames[i - 1]);
          const old = (previous.bond_state as unknown[][])[b];
          if (old?.[0] === false && bond[0] === true)
            throw new Error("Recording healed a bond");
        }
      }
    }
  }
  return value as Recording;
}
export function validateResult(
  value: unknown,
  expected: ExperimentRequest,
): ExperimentResult {
  const result = object(value);
  const request = validateRequest(result.request);
  const recording = validateRecording(result.recording);
  const identity = object(result.identity);
  if (
    result.schema !== "banjo.material-lab-result.v1" ||
    result.status !== "completed" ||
    typeof result.execution_id !== "string" ||
    !/^[a-f0-9]{32}$/.test(result.execution_id) ||
    !finite(result.elapsed_wall_s) ||
    result.elapsed_wall_s <= 0 ||
    request.force_scale !== expected.force_scale ||
    recording.request.force_scale !== request.force_scale ||
    ![
      identity.native_sha256,
      identity.request_sha256,
      identity.recording_sha256,
    ].every((v) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v))
  )
    throw new Error("Incomplete or mismatched experiment result");
  return value as ExperimentResult;
}
