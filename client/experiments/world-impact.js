// Presentation of measured native evidence; never predicts a fracture.
export function impactRows(report){
    const hit=report.actual?.physical_hit;
    const number=(value,unit,digits=3)=>Number.isFinite(value)?value.toFixed(digits)+' '+unit:'Unavailable';
    return [
        ['Requested point',report.requested_target_m.map(v=>v.toFixed(3)).join(', ')+' m'],
        ['Engine admission',report.expectation.native_preview?.admitted?'Allowed (contact not guaranteed)':report.expectation.native_preview?.reason || 'Unavailable'],
        ['Model expectation','Rigid collision; no breakage prediction'],
        ['Actual result',hit?(hit.contacted?'Target contacted':hit.reason || 'No confirmed contact'):report.command_outcome?.reason || report.status],
        ['Target',hit?.target || report.expectation.native_preview?.target || 'Unavailable'],
        ['Resolved contact point',hit?.target_m?hit.target_m.map(v=>v.toFixed(3)).join(', ')+' m':'Unavailable'],
        ['Contact part',hit?.contact_part || 'None confirmed'],
        ['Obstruction',hit?.obstruction || 'None reported'],
        ['Contact speed',number(hit?.contact_speed_m_s,'m/s')],
        ['Peak tool-tip speed',number(hit?.peak_tip_speed_m_s,'m/s')],
        ['Swing rotation',number(hit?.swing_rotation_rad,'rad')],
        ['Target travel',hit?number(Math.hypot(...hit.target_displacement_m)*100,'cm'):'Unavailable'],
        ['Signed hand work',number(hit?.hand_work_j,'J')],
        ['Native duration',hit?number(hit.ended_s-hit.started_s,'s'):'Unavailable'],
        ['Controller end',hit?.stroke_ended || hit?.phase || report.status],
        ['New bodies observed',report.actual?String(report.actual.observed_new_bodies.length):'Unavailable'],
        ['Removed bodies observed',report.actual?String(report.actual.observed_removed_bodies.length):'Unavailable'],
        ['Observed body mass change',number(report.actual?.observed_body_mass_change_kg,'kg',6)],
        ['Cracks / broken bonds','Unavailable — fracture is not connected'],
        ['Contact impulse / full energy balance','Not exported / not qualified']
    ];
}
