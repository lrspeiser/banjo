"""Resident Newton/Warp rigid contact stage; fracture/elastic laws are not ported.

Only bounded numeric declarations enter this module. Renderer-independent states
are emitted from actual solver arrays. No prescribed post-contact trajectories.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import math
from pathlib import Path
import sys
import time

with contextlib.redirect_stdout(sys.stderr):
    import numpy as np
    import newton
    import warp as wp
    wp.config.quiet = True
    wp.init()

if (newton.__version__, wp.__version__, np.__version__) != ("1.6.1", "1.18.0", "2.5.3"):
    raise RuntimeError("Unverified runtime versions; install scripts/gpu-requirements.txt")

DENSITY = {"glass": 2500., "oak": 700., "iron": 7870., "ice": 917.}
VERSION = "banjo.newton-rigid-contact.v1"
SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@wp.kernel
def check_capacity(count: wp.array[int], capacity: int, faults: wp.array[int]):
    if count[0] < 0 or count[0] > capacity:
        wp.atomic_max(faults, 0, 2)


@wp.kernel
def record_step(q: wp.array[wp.transform], qd: wp.array[wp.spatial_vector],
                contacts: wp.array[int], poses: wp.array[wp.transform],
                velocities: wp.array[wp.spatial_vector], counts: wp.array[int],
                faults: wp.array[int], slot: int, bodies: int, capacity: int):
    i = wp.tid()
    poses[slot*bodies+i] = q[i]
    velocities[slot*bodies+i] = qd[i]
    for j in range(7):
        if not wp.isfinite(q[i][j]):
            wp.atomic_max(faults, 0, 1)
    for j in range(6):
        if not wp.isfinite(qd[i][j]):
            wp.atomic_max(faults, 0, 1)
    if i == 0:
        counts[slot] = contacts[0]
        if contacts[0] > capacity:
            wp.atomic_max(faults, 0, 2)


def declaration(raw):
    if not isinstance(raw, dict):
        raise ValueError("Declaration must be an object")
    defaults = dict(experiment="floor", material="glass", ball_material="iron",
                    height_m=10., ball_mass_kg=1., restitution=0.5, friction=0.3,
                    dt_s=1/960, offset_m=0., device="cuda:0", solver_relaxation=0.1)
    if set(raw) - set(defaults):
        raise ValueError("Unknown GPU scene field")
    d = defaults | raw
    for key in ("experiment", "material", "ball_material", "device"):
        if type(d[key]) is not str:
            raise ValueError(f"Invalid {key}")
    if d["experiment"] not in ("yard", "floor", "pair", "freefall"):
        raise ValueError("Unknown experiment")
    if d["material"] not in DENSITY or d["ball_material"] not in DENSITY:
        raise ValueError("Material not admitted")
    if d["device"] not in ("cuda:0", "cpu"):
        raise ValueError("Device must be cuda:0 or the explicit CPU reference")
    for key, lo, hi in (("height_m", .1, 10.), ("ball_mass_kg", .1, 5.),
                        ("restitution", 0., .9), ("friction", 0., .8),
                        ("offset_m", -.15, .15)):
        if type(d[key]) not in (float, int) or not math.isfinite(d[key]) or not lo <= d[key] <= hi:
            raise ValueError(f"Invalid {key}")
    if type(d["dt_s"]) not in (float, int) or d["dt_s"] not in (1/240, 1/480, 1/960, 1/1920):
        raise ValueError("Unadmitted timestep")
    if type(d["solver_relaxation"]) not in (float, int) or d["solver_relaxation"] not in (.1, .2, .4, .8, 1.):
        raise ValueError("Unadmitted relaxation")
    # Only the contact controls use coarse steps: an iron ball of 0.1 kg
    # from 10 m can traverse a large fraction of its diameter in 1/240 s.
    if d["experiment"] in ("yard", "floor") and d["dt_s"] > 1/960:
        raise ValueError("Drop tests require 1/960 s or finer; CCD is not implemented")
    return d


class GpuContactWorld:
    def __init__(self, raw):
        self.d = declaration(raw)
        self.device = wp.get_device(self.d["device"])
        if self.d["device"] != "cpu" and not self.device.is_cuda:
            raise ValueError("GPU requested but unavailable; no silent CPU fallback")
        self.ticks = 0
        self.total_step_s = 0.
        self.last_batch_s = 0.
        self.max_contacts = 0
        self.graphs = {}
        self.last_steps = 0
        self.metadata = []
        self.gravity = 0. if self.d["experiment"] == "pair" else -9.81
        builder = newton.ModelBuilder(up_axis=newton.Axis.Y, gravity=(0., self.gravity, 0.))
        cfg = newton.ModelBuilder.ShapeConfig(
            restitution=self.d["restitution"], mu=self.d["friction"],
            mu_torsional=0., mu_rolling=0., margin=0., gap=0.002)

        def config(density):
            result = copy.copy(cfg)
            result.density = density
            return result

        def sphere(material, mass, position, velocity=(0., 0., 0.)):
            radius = (mass/(DENSITY[material]*4*math.pi/3))**(1/3)
            body = builder.add_body(xform=wp.transform(wp.vec3(*position), wp.quat_identity()))
            builder.add_shape_sphere(body, radius=radius, cfg=config(DENSITY[material]))
            builder.body_qd[body] = wp.spatial_vector(*velocity, 0., 0., 0.)
            self.metadata.append(dict(id=body, material=material, shape="sphere", radius_m=radius,
                                      size_m=[2*radius]*3, expected_mass_kg=mass))
            return radius

        if self.d["experiment"] == "pair":
            sphere(self.d["ball_material"], self.d["ball_mass_kg"], (-.2, 0., self.d["offset_m"]), (2., 0., 0.))
            sphere(self.d["material"], self.d["ball_mass_kg"], (.2, 0., 0.))
        else:
            if self.d["experiment"] != "freefall":
                builder.add_ground_plane(cfg=config(2400.))
            top = 0.
            if self.d["experiment"] == "yard":
                side = .12
                for level in range(3):
                    for x in range(-1, 2):
                        for z in range(-1, 2):
                            body = builder.add_body(xform=wp.transform(
                                wp.vec3(x*(side+.0002), side/2+level*(side+.0002), z*(side+.0002)),
                                wp.quat_identity()))
                            builder.add_shape_box(body, hx=side/2, hy=side/2, hz=side/2,
                                                  cfg=config(DENSITY[self.d["material"]]))
                            self.metadata.append(dict(id=body, material=self.d["material"], shape="box",
                                                      size_m=[side]*3, expected_mass_kg=DENSITY[self.d["material"]]*side**3))
                top = side*3 + .0004
            mass = self.d["ball_mass_kg"]
            r = (mass/(DENSITY[self.d["ball_material"]]*4*math.pi/3))**(1/3)
            sphere(self.d["ball_material"], mass, (self.d["offset_m"], top+r+self.d["height_m"], 0.))
        self.model = builder.finalize(device=self.device)
        self.model.request_contact_attributes("force")
        self.states = [self.model.state(), self.model.state()]
        self.state = self.states[0]
        self.control = self.model.control()
        # Weighting is explicitly disabled: its per-body 1/contact-count factor
        # is incompatible with a symmetric impulse account for unequal counts.
        self.solver = newton.solvers.SolverXPBD(self.model, iterations=16,
            rigid_contact_con_weighting=False, rigid_contact_relaxation=self.d["solver_relaxation"],
            rigid_contact_restitution_iterations=4, enable_restitution=True,
            angular_damping=0.)
        self.pipeline = newton.CollisionPipeline(self.model, rigid_contact_max=4096,
                                                shape_pairs_max=4096, verify_buffers=False)
        # Library verify_buffers only prints warnings (and can corrupt a JSON
        # stdout transport). Our GPU counters below refuse/rollback a batch.
        self.contacts = self.pipeline.contacts()
        n = len(self.metadata)
        self.trace_q = wp.empty(32*n, dtype=wp.transform, device=self.device)
        self.trace_qd = wp.empty(32*n, dtype=wp.spatial_vector, device=self.device)
        self.trace_contacts = wp.zeros(32, dtype=int, device=self.device)
        self.trace_faults = wp.zeros(1, dtype=int, device=self.device)
        narrow = self.pipeline.narrow_phase
        self.capacity_checks = [(self.pipeline.broad_phase_pair_count, self.pipeline.shape_pairs_max)]
        for count_name, buffer_name in (
            ("gjk_candidate_pairs_count", "gjk_candidate_pairs"),
            ("split_gjk_work_count", "split_gjk_work_items"),
            ("split_manifold_work_count", "split_manifold_work_items"),
            ("shape_pairs_mesh_count", "shape_pairs_mesh"),
            ("triangle_pairs_count", "triangle_pairs"),
            ("shape_pairs_mesh_plane_count", "shape_pairs_mesh_plane"),
            ("shape_pairs_mesh_mesh_count", "shape_pairs_mesh_mesh"),
            ("shape_pairs_sdf_sdf_count", "shape_pairs_sdf_sdf")):
            count, buffer = getattr(narrow, count_name), getattr(narrow, buffer_name)
            if count is not None:
                self.capacity_checks.append((count, buffer.shape[0] if buffer is not None else 0))
        if narrow.split_gjk_mpr:
            self.capacity_checks.append((self.pipeline.broad_phase_pair_count if narrow.sparse_gjk_pairs
                else narrow.gjk_candidate_pairs_count, narrow.split_query_results.shape[0]))
        if narrow.global_contact_reducer is not None:
            self.capacity_checks.append((narrow.global_contact_reducer.ht_insert_failures, 0))
        self.mass = self.model.body_mass.numpy().astype(np.float64)
        self.inertia = self.model.body_inertia.numpy().astype(np.float64)
        # The admitted solid cubes and spheres have isotropic inertia; this
        # permits a frame-independent exact kinetic audit of every saved step.
        self.inertia_scalar = self.inertia[:, 0, 0]
        if not np.allclose(self.inertia, self.inertia_scalar[:, None, None]*np.eye(3), rtol=2e-6, atol=1e-12):
            raise ValueError("Non-isotropic geometry needs a rotated-inertia audit")
        for row, actual in zip(self.metadata, self.mass):
            if not math.isclose(row["expected_mass_kg"], actual, rel_tol=2e-6):
                raise ValueError("Geometry-derived mass mismatch")
        self.initial_q = wp.clone(self.state.body_q)
        self.initial_qd = wp.clone(self.state.body_qd)
        self.saved_q = wp.clone(self.state.body_q)
        self.saved_qd = wp.clone(self.state.body_qd)
        # Warm library buffers and compilation before admission to an experiment.
        # Restore the declared initial state once; never prescribe later motion.
        with contextlib.redirect_stdout(sys.stderr), wp.ScopedDevice(self.device):
            self._step()
            wp.copy(self.states[0].body_q, self.initial_q)
            wp.copy(self.states[1].body_q, self.initial_q)
            wp.copy(self.states[0].body_qd, self.initial_qd)
            wp.copy(self.states[1].body_qd, self.initial_qd)
            self.state = self.states[0]
            self.contacts.clear()
        self.initial = self.snapshot()
        self.accepted_snapshot = copy.deepcopy(self.initial)
        self.last_energy = self.initial["diagnostics"]["mechanical_j"]
        self.max_candidate_gain_j = 0.

    def _step(self):
        self.state.clear_forces()
        self.pipeline.collide(self.state, self.contacts)
        target = self.states[1] if self.state is self.states[0] else self.states[0]
        self.solver.step(self.state, target, self.control, self.contacts, self.d["dt_s"])
        self.solver.update_contacts(self.contacts)
        self.state = target

    def advance(self, steps):
        if hasattr(self, "rejected_candidate"):
            raise ValueError("Rejected GPU experiment is stopped; reset is required")
        if type(steps) is not int or not 1 <= steps <= 32 or self.ticks+steps > round(4/self.d["dt_s"]):
            raise ValueError("Steps outside the bounded experiment")
        started = time.perf_counter()
        wp.copy(self.saved_q, self.state.body_q)
        wp.copy(self.saved_qd, self.state.body_qd)
        with contextlib.redirect_stdout(sys.stderr), wp.ScopedDevice(self.device):
            key = (steps, self.state is self.states[0])
            # Both pose buffers remain resident; the captured graph contains the
            # same collision/solver/observation operations as the CPU schedule.
            if self.device.is_cuda:
                if key not in self.graphs:
                    with wp.ScopedCapture(device=self.device) as capture:
                        self._batch(steps)
                    self.graphs[key] = (capture.graph, self.state)
                graph, target = self.graphs[key]
                wp.capture_launch(graph)
                self.state = target
            else:
                self._batch(steps)
            wp.synchronize_device(self.device)
        poses = self.trace_q.numpy()[:steps*len(self.mass)].reshape(steps, len(self.mass), 7).astype(np.float64)
        velocities = self.trace_qd.numpy()[:steps*len(self.mass)].reshape(steps, len(self.mass), 6).astype(np.float64)
        energies = .5*np.sum(self.mass[None, :, None]*velocities[:, :, :3]**2, axis=(1, 2))
        energies += .5*np.sum(self.inertia_scalar[None, :, None]*velocities[:, :, 3:]**2, axis=(1, 2))
        energies -= self.gravity*np.sum(self.mass[None, :]*poses[:, :, 1], axis=1)
        previous = np.concatenate(([self.last_energy], energies[:-1]))
        gains = energies-previous
        self.max_candidate_gain_j = max(self.max_candidate_gain_j, float(gains.max()))
        tolerance = 1e-5*np.maximum(1., np.abs(previous)) + 1e-6
        fault = bool(self.trace_faults.numpy()[0])
        if fault or not np.isfinite(energies).all() or np.any(gains > tolerance):
            for state in self.states:
                wp.copy(state.body_q, self.saved_q)
                wp.copy(state.body_qd, self.saved_qd)
            safe = lambda xs: [float(x) if math.isfinite(x) else None for x in xs]
            self.rejected_candidate = dict(first_tick=self.ticks+1,
                                           max_gain_j=float(gains.max()) if np.isfinite(gains).all() else None,
                                           energy_j=safe(energies), tolerance_j=safe(tolerance),
                                           contact_counts=self.trace_contacts.numpy()[:steps].tolist(),
                                           faults=int(self.trace_faults.numpy()[0]))
            raise ValueError("GPU candidate refused: intermediate capacity/finite/energy gate; previous accepted state retained")
        self.last_batch_s = time.perf_counter()-started
        self.total_step_s += self.last_batch_s
        self.ticks += steps
        self.last_steps = steps
        self.last_energy = float(energies[-1])
        result = self.snapshot()
        self.accepted_snapshot = copy.deepcopy(result)
        return result

    def _batch(self, steps):
        self.trace_faults.zero_()
        for index in range(steps):
            self._step()
            for count, capacity in self.capacity_checks:
                wp.launch(check_capacity, dim=1, inputs=[count, capacity, self.trace_faults], device=self.device)
            wp.launch(record_step, dim=len(self.metadata), inputs=[
                self.state.body_q, self.state.body_qd, self.contacts.rigid_contact_count,
                self.trace_q, self.trace_qd, self.trace_contacts, self.trace_faults,
                index, len(self.metadata), self.contacts.rigid_contact_max], device=self.device)

    def snapshot(self):
        if hasattr(self, "rejected_candidate"):
            result = copy.deepcopy(self.accepted_snapshot)
            result["rejected_candidate"] = copy.deepcopy(self.rejected_candidate)
            return result
        q = self.state.body_q.numpy().astype(np.float64)
        qd = self.state.body_qd.numpy().astype(np.float64)
        if not np.isfinite(q).all() or not np.isfinite(qd).all():
            raise ValueError("Nonfinite state refused")
        # Actual body COM is at its shape origin for these admitted solid shapes.
        p = np.sum(self.mass[:, None]*qd[:, :3], axis=0)
        spin = []
        rotational = 0.
        for i in range(len(q)):
            rotation = np.array(wp.quat_to_matrix(wp.quat(*q[i, 3:].astype(np.float32)))).reshape(3, 3).astype(np.float64)
            inertia = rotation @ self.inertia[i] @ rotation.T
            spin.append(inertia @ qd[i, 3:])
            rotational += .5*qd[i, 3:] @ inertia @ qd[i, 3:]
        angular = np.sum(np.cross(q[:, :3], self.mass[:, None]*qd[:, :3])+spin, axis=0)
        kinetic = .5*np.sum(self.mass[:, None]*qd[:, :3]**2)+rotational
        potential = -self.gravity*np.sum(self.mass*q[:, 1])
        count = int(self.contacts.rigid_contact_count.numpy()[0])
        if count > self.contacts.rigid_contact_max:
            raise ValueError("Contact buffer overflow; candidate is not admitted")
        trace_counts = self.trace_contacts.numpy()[:self.last_steps]
        self.max_contacts = max(self.max_contacts, count, int(trace_counts.max()) if len(trace_counts) else 0)
        # These are actual library-reported constraint wrenches. In Newton 1.6.1
        # the later restitution solve is not included in update_contacts(); this
        # is explicitly incomplete, not an invented ground-reaction ledger.
        forces = self.contacts.force.numpy()[:count].astype(np.float64)
        cells = [row | dict(mass_kg=float(self.mass[i]), position_m=q[i, :3].tolist(),
                 quaternion_wxyz=[float(q[i, 6]), *q[i, 3:6].tolist()], velocity_m_s=qd[i, :3].tolist(),
                 angular_velocity_rad_s=qd[i, 3:].tolist(), fixed=False, component=i+1)
                 for i, row in enumerate(self.metadata)]
        energy = float(kinetic+potential)
        initial_e = self.initial["diagnostics"]["mechanical_j"] if hasattr(self, "initial") else energy
        trace = dict(first_tick=self.ticks-self.last_steps+1, transform_layout="xyz,xyzw",
                     body_ids=[row["id"] for row in self.metadata], contact_counts=trace_counts.tolist(),
                     transforms=self.trace_q.numpy()[:self.last_steps*len(q)].reshape(self.last_steps, len(q), 7).tolist(),
                     velocities_v_omega=self.trace_qd.numpy()[:self.last_steps*len(q)].reshape(self.last_steps, len(q), 6).tolist())
        return dict(schema=VERSION, declaration=copy.deepcopy(self.d), time_s=self.ticks*self.d["dt_s"],
                    ticks=self.ticks, dt_s=self.d["dt_s"], cells=cells, events=[],
                    substep_trace=trace,
                    diagnostics=dict(dynamic_mass_kg=float(self.mass.sum()), kinetic_j=float(kinetic),
                        potential_j=float(potential), mechanical_j=energy, mechanical_change_j=energy-initial_e,
                        momentum_n_s=p.tolist(), angular_momentum_n_m_s=angular.tolist(),
                        contacts=count, max_contacts=self.max_contacts,
                        last_constraint_wrenches_n_n_m=forces.tolist() if forces is not None else None,
                        reaction_account_complete=False, numerical_and_contact_losses_separated=False),
                    performance=dict(step_s=self.total_step_s, last_batch_ms=self.last_batch_s*1000,
                                     compute_ratio=(self.ticks*self.d["dt_s"])/self.total_step_s if self.total_step_s else None),
                    qualification=dict(backend="newton-xpbd", newton=newton.__version__, warp=wp.__version__,
                        device=str(self.device), gpu=self.device.is_cuda,
                        device_name=self.device.name, source_sha256=SOURCE_SHA256, dtype="float32",
                        contact_weighting=False, angular_damping=0.,
                        material_scope="Density-derived rigid mass/inertia; declared global restitution/friction. No elastic, fracture, plastic, grain or thermal law.",
                        complete_physics_validated=False, realtime_qualified=False))
