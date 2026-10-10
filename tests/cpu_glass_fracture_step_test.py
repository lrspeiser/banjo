"""A glass sheet breaking under a 10 m drop: the step that used to be refused.

The saved step (tests/data/coupled-glass-high-drop-step.json) is the one the
CPU lab refused at 1.425 s. Its glass interfaces soften past their strength:
their force falls as they open, faster than the cells' inertia can follow at
a few microseconds, so the step's equations have no locally unique root and
Newton stalls. This test shows that, shows the controller's softening bound
picks a step at which inertia wins again, and that the step then converges and
closes its energy and momentum like any other. With --full it also runs the
whole 2 s drop through the world's controller.
"""
import argparse, json, math, os, sys, time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def main(args):
    os.environ['BANJO_COUPLED_CPU_LIBRARY'] = str(args.library.resolve())
    from coupled_solver import TrialFailure
    from coupled_world import CoupledWorld, SUBDIVISION_DEPTH
    from cpu_coupled_world import CpuCoupledEvaluator, CpuCoupledWorld
    saved = json.loads((ROOT / 'tests/data/coupled-glass-high-drop-step.json').read_text(encoding='utf-8'))
    bodies, edges, h = np.array(saved['bodies']), np.array(saved['edges']), saved['dt_s']
    report = dict(step_s=h)

    # 1. At the saved step Newton stalls with interfaces past their strength.
    evaluator = CpuCoupledEvaluator(bodies, edges, pipeline='local-jacobian')
    try:
        evaluator.solve(h)
        raise AssertionError('the saved step was expected to stall')
    except TrialFailure as error:
        details = error.details
    trial = np.array(details['last_evaluated']['material_history'][0])
    d0 = edges[:, 19] / edges[:, 18]
    df = 2 * edges[:, 20] / edges[:, 19]
    crossed = (trial[:, 1] > d0) & (edges[:, 36] < df)
    softening = crossed & (trial[:, 1] < df)
    assert softening.any(), 'the stalled trial left no interface softening'
    report.update(stalled_residual=details['iterations'][-1]['equation_residual'],
                  interfaces_past_strength=int(crossed.sum()), interfaces_softening=int(softening.sum()))

    # 2. The softening bound: the mass each interface the trial took past its
    # strength pulls on, against its softening rate, k_s = A*strength/(df-d0).
    world = SimpleNamespace(eval=evaluator, to_host=np.asarray)
    levels = CoupledWorld.softening_levels(world, details, h, 10)
    step = h / 2 ** levels
    k_s = edges[:, 21] * edges[:, 19] / (df - d0)
    load = np.zeros(len(bodies))
    for edge, rate, active in zip(edges, k_s, crossed):
        if active:
            load[int(edge[0])] += rate
            load[int(edge[1])] += rate
    pulled = (load > 0) & (bodies[:, 1] > 0)
    bound = math.sqrt(np.min(bodies[pulled, 1] / load[pulled]))
    assert 1 < levels <= SUBDIVISION_DEPTH - 10 and bound / 2 < step <= bound, (levels, step, bound)
    report.update(softening_bound_s=bound, chosen_step_s=step, skipped_halvings=levels - 1)

    # 3. At that step the same equations converge, and the step closes its
    # energy (with the fracture and contact ledgers) and momentum.
    evaluator = CpuCoupledEvaluator(bodies, edges, pipeline='local-jacobian')
    out, velocity, iterations, residual = evaluator.solve(step)
    ending = bodies.copy()
    ending[:, 7:14] = out['poses']
    ending[:, 14:20] = velocity
    energy0, p0, _ = CpuCoupledWorld.mechanics(bodies)
    energy1, p1, _ = CpuCoupledWorld.mechanics(ending)
    ledger = out['ledger']
    balance = energy1 - energy0 + ledger[1] - ledger[0] + ledger[2] + ledger[3] + ledger[5] - ledger[4]
    tolerance = 1e-10 + 1e-8 * max(abs(energy0 + ledger[0] + ledger[4]), 1e-3)
    fixed = bodies[:, 1] == 0
    impulse = -step * out['forces'][fixed, :3].sum(axis=0) + np.array([0, -9.81 * bodies[:, 1].sum() * step, 0])
    assert abs(balance) <= tolerance, (balance, tolerance)
    assert np.linalg.norm(p1 - p0 - impulse) < 1e-9
    assert int(out['faults']) == 0
    report.update(iterations=iterations, equation_residual=residual, energy_residual_j=balance,
                  energy_tolerance_j=tolerance, fracture_j=float(ledger[2]))
    print('stalled at %.3g s with %d interfaces past strength, %d softening; bound %.3g s, step %.3g s converged '
          'in %d iterations, energy residual %.2e J' % (h, int(crossed.sum()), int(softening.sum()), bound, step, iterations,
                                                         balance),
          flush=True)

    # 4. The whole drop through the world's controller (minutes; --full only),
    # with the centre cell heated: heat crosses each face only through its
    # bonded part, so once the sheet has broken apart no other cell warms.
    if args.full:
        os.environ.setdefault('BANJO_THERMAL_FIELDS_LIBRARY', str(args.library.resolve().with_name(
            args.library.name.replace('banjo_coupled_cpu', 'banjo_thermal_fields'))))
        w = CpuCoupledWorld(dict(material='glass', ball_material='iron', ball_mass_kg=.1, height_m=10, dt_s=1 / 240,
                                 experiment='sheet', pipeline='local-jacobian', representation_policy='partitioned-flight',
                                 thermal=dict(initial_temperature_k=260., heater_w=2., heater_body_id=7)))
        started = time.perf_counter()
        apart = None
        while w.time < 2 - 1e-9:
            w.advance(1)
            if apart is None and np.all(w.histories[:, 6] == 1):
                apart = (w.time, [list(t) for t in w.fields.observations()])
        broken = int(np.sum(w.histories[:, 6] == 1))
        expected = float(np.sum(w.eval.edges[:, 20] * w.eval.edges[:, 21]))
        assert broken == len(w.histories), broken
        assert math.isclose(w.fracture, expected, rel_tol=1e-9), (w.fracture, expected)
        assert w.max_residual < 1e-8
        # Heat: every face separated carries nothing; the other cells kept the
        # temperature they had when the last face broke; the combined account
        # (mechanics, storage, fracture and heat) closes.
        assert apart is not None and all(link[2] == 0 for link in w.fields.links)
        now = w.fields.observations()
        centre = next(i for i, r in enumerate(w.fields.mapping) if r['body_id'] == 7)
        for i, r in enumerate(w.fields.mapping):
            if i != centre and r['body_id'] in range(3, 12):
                assert now[i][0] == apart[1][i][0], (r['body_id'], now[i][0], apart[1][i][0])
        s = w.snapshot()
        f, d = s['thermal_fields'], s['diagnostics']
        heat = math.fsum(cell['thermal_energy_j'] for cell in f['fields'])
        account = (d['mechanical_j'] + d['material_stored_j'] + d['contact_stored_j'] + d['fracture_work_j']
                   + d['plastic_work_j'] + d['numerical_return_excess_j'])
        combined = account + heat - w.initial_energy - w.fields.initial_energy - f['audit']['external_heat_j']
        assert abs(combined) < 1e-8, combined
        saved = w.export_checkpoint()
        reopened = CpuCoupledWorld.from_checkpoint(saved)
        assert reopened.export_checkpoint() == saved and reopened.fields.links == w.fields.links
        report.update(full_drop=dict(physical_s=w.time, wall_s=time.perf_counter() - started, broken=broken,
                                     fracture_j=w.fracture, max_energy_residual_j=w.max_residual,
                                     substeps=w.microsteps, separated_at_s=apart[0],
                                     centre_temperature_k=now[centre][0], combined_energy_residual_j=combined))
        print('2 s drop: %d of %d interfaces broken, fracture %.4g J, max energy residual %.2e J, %d substeps, '
              '%.0f s wall; all faces apart at %.4f s, centre cell %.3f K, combined energy residual %.2e J'
              % (broken, len(w.histories), w.fracture, w.max_residual, w.microsteps, time.perf_counter() - started,
                 apart[0], now[centre][0], combined), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--full', action='store_true')
    main(parser.parse_args())
