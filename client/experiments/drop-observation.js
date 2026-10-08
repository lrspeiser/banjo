// Explanations use observed state and supported laws, never display-name outcomes.
export function describeObservation(before, after) {
  if (!before || !after) return 'Prepare an experiment to capture its before state.';
  const r=after.report;
  if (!r.state_valid) return 'Incomplete result: a native update was refused. Inspect the log; damage is not qualified.';
  if (r.experiment==='water-wheel') {
    if (!r.water_particles) return 'Dry control: the wheel should stay still. Observed rotation: '+r.wheel_angle_rad.toFixed(3)+' rad.';
    const moved=Math.abs(r.wheel_angle_rad)>.01&&r.water_wheel_contact_events>0;
    return (moved?'Water fell onto the paddles and the unpowered wheel turned.':'Water has not measurably turned the wheel yet. Continue until it reaches the paddles; a missed stream should leave the wheel still.')+
      ' Rotation: '+r.wheel_angle_rad.toFixed(3)+' rad; wheel energy: '+r.wheel_kinetic_energy_j.toFixed(3)+' J. '+
      (moved?'This looks consistent with falling water transferring momentum. ':'No contact-driven rotation is established yet. ')+
      'The visible parcels use experimental pressure/viscosity and sphere contact; splash shape is not calibrated. Paddles are rigid, so this does not test wood bending or breakage.';
  }
  if (after.declaration.mode==='rigid') return 'Intact rigid baseline: the ball and sheet move or rebound. No fracture or dent is implemented in this mode.';
  return r.objects.filter(o=>o.id===1||o.id===2).map(o=>{
    const old=before.report.objects.find(v=>v.id===o.id),label=o.id===1?'Sheet':'Ball';
    const first=new Map(before.instances.filter(i=>i.object_id===o.id).map(i=>[i.element_id,i]));
    const current=after.instances.filter(i=>i.object_id===o.id);
    let displacement=0;for(const i of current){const a=first.get(i.element_id);if(a)displacement=Math.max(displacement,Math.hypot(...i.position_m.map((x,k)=>x-a.position_m[k])));}
    if(o.broken_links>old.broken_links) return `${label}: ${o.broken_links-old.broken_links} bonds broke; ${o.components===1?'still one connected piece, with no separate fragments':o.components+' connected pieces, identified by color'}. Largest cell travel ${(displacement*1000).toFixed(1)} mm. ${displacement<.005?'Visible scattering is not established in this short observation.':'Cells have moved; inspect the after view for separation.'} Realistic shards remain unqualified.`;
    if(o.plastic_work_j>old.plastic_work_j+1e-8) return `${label}: no broken bonds; ${(o.plastic_work_j-old.plastic_work_j).toFixed(3)} J of axial plastic work. Largest cell travel ${(displacement*1000).toFixed(1)} mm. Permanent axial deformation is recorded; ${o.id===1?'a realistic plate dent needs unloading and bending validation':'a realistic deformed ball needs unloading and material validation'}. The final shape is not established by this early view.`;
    return `${label}: no observed fracture or plastic change. Largest cell travel ${(displacement*1000).toFixed(1)} mm; motion alone can be rigid displacement or elastic deformation.`;
  }).join(' ');
}
