"""The ball lands where it is let go: a drop spot on the coupled lab's sheet.

A 1 mm drop aimed over each corner cell and over the centre first touches the
cell under it (measured from the solver's own contact sites), the accounts of
that step close, and a spot off the sheet is refused.
"""
import argparse, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def main(args):
    os.environ['BANJO_COUPLED_CPU_LIBRARY'] = str(args.library.resolve())
    from cpu_coupled_world import CpuCoupledWorld
    # The sheet's cells are bodies 3..11, laid out x-major: body 3 + 3*i + k
    # sits at x = (i-1)*10 mm, z = (k-1)*10 mm. The ball is the last body.
    for spot in ([.01, -.01], [-.01, .01], [0., 0.], [.012, .012]):
        i, k = (round(spot[0] / .01) + 1, round(spot[1] / .01) + 1)
        under = 3 + 3 * i + k
        w = CpuCoupledWorld(dict(material='glass', ball_material='iron', ball_mass_kg=.1, height_m=.001, dt_s=1 / 240,
                                 experiment='sheet', pipeline='local-jacobian', spot_m=spot))
        ball = len(w.eval.bodies) - 1
        assert abs(w.eval.bodies[ball, 7] - spot[0]) < 1e-15 and abs(w.eval.bodies[ball, 9] - spot[1]) < 1e-15
        first = None
        while first is None and w.time < .1:
            s = w.advance(1)
            for account in s['substep_accounts']:
                assert abs(account['energy_residual_j']) <= account['energy_tolerance_j']
                touched = {b for site in account['contact_samples'] or [] for b in site['body_ids']
                           if ball in site['body_ids'] and b != ball}
                if touched:
                    first = touched
                    break
        assert first == {under}, (spot, first, under)
        print('spot', spot, 'first touches cell body', sorted(first), 'at', round(w.time, 4), 's', flush=True)
    for bad in ([.016, 0], [0, -.02], [0], [float('nan'), 0]):
        try:
            CpuCoupledWorld(dict(material='glass', height_m=.001, spot_m=bad))
            raise AssertionError('a spot off the sheet was admitted: %r' % (bad,))
        except ValueError:
            pass
    print('PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', type=Path, required=True)
    main(parser.parse_args())
