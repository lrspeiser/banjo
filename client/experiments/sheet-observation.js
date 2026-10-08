// Diagnostic geometry follows the accepted native state. These lines identify
// severed axial connections; they are not authored crack surfaces or fragments.
export function brokenBondSegments(state) {
  const points = [];
  for (const [a, b] of state.broken_interfaces) {
    for (const id of [a, b]) {
      const p = state.positions[id];
      if (!p || !p.slice(0, 3).every(Number.isFinite)) throw Error('Invalid broken bond endpoint');
      points.push(...p.slice(0, 3));
    }
  }
  return points;
}

export function describeSheet(state, failure = '') {
  const seconds = state.time_s.toExponential(3);
  if (!state.steps) return 'Ready: no impact has been simulated.';
  const damage = state.broken_bonds ? `${state.broken_bonds} connections broke; ${state.detached_cells} cells detached.` : 'No connections broke.';
  const opening = state.open_columns ? `${state.open_columns} through-thickness probes are clear. This is not calibrated material fracture.` : 'No clear through-thickness opening has been observed.';
  return `${failure ? 'Native contact refused: '+failure+' Last accepted state retained. ' : ''}${seconds} s simulated. ${damage} ${opening} Broken connections may remain touching, so they may not form a visible crack.`;
}
