import * as THREE from '/vendor/three.module.js';

// Native RunKind values include loose/weathered source classes. Rendering
// keeps those source names without claiming that ore is refined metal.
const runNames=['rock','soil','sand','loose soil','weathered rock','clay','ore','oxide ore'];
const runKinds=['rock','soil','sand','soil','rock','soil','rock','rock'];
const kindOf=cell=>typeof cell.run_kind==='number' ? runKinds[cell.run_kind] || 'rock' : cell.run_kind;
const nameOf=cell=>typeof cell.run_kind==='number' ? runNames[cell.run_kind] || cell.material || 'resource' : cell.run_kind || cell.material || 'resource';

export function looseGroundLabel(answer,yielded,massLabel,title=value=>value) {
  if(!answer.physical_ground && !answer.cut?.body_id)return null;
  const kg=yielded?.kg || answer.cut?.mass_kg;
  const materials=yielded?.materials || [answer.cut?.ground || 'material'];
  if(!(kg>0))return null;
  return `Loose ${materials.map(title).join(' + ')} · ${massLabel(kg)} · click to collect`;
}

// Draw only native constituent geometry and native poses. There are no
// receipt particles, launch paths or pile reconstruction in this adapter.
export function makePhysicalGround({scene,camera,world,api,whereIAm,lastAction,showInventory}) {
  const root=new THREE.Group();root.name='native-ground-matter';scene.add(root);
  const bodies=new Map(),collected=new Set(),materials=new Map(),ray=new THREE.Raycaster();
  const colors={rock:0x8d9197,soil:0x745037,sand:0xd2b877};
  let busy=false;
  const materialFor=kind=>{
    if(!materials.has(kind))materials.set(kind,new THREE.MeshStandardMaterial({color:colors[kind]??0x8d9197,roughness:.95}));
    return materials.get(kind);
  };
  function buildGeometry(entry,body) {
    for(const mesh of [...entry.group.children]){entry.group.remove(mesh);mesh.geometry?.dispose();}
    const origin=new THREE.Vector3(...body.source_center_m),byKind=new Map();
    for(const cell of body.cells?.length ? body.cells : body.slabs || []) {
      const kind=kindOf(cell);
      if(!byKind.has(kind))byKind.set(kind,[]);
      byKind.get(kind).push(cell);
    }
    for(const [kind,cells] of byKind) {
      const mesh=new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1),materialFor(kind),cells.length);
      const matrix=new THREE.Matrix4(),position=new THREE.Vector3(),scale=new THREE.Vector3(),q=new THREE.Quaternion();
      for(let i=0;i<cells.length;i++) {
        position.fromArray(cells[i].source_center_m).sub(origin);scale.fromArray(cells[i].size_m);
        mesh.setMatrixAt(i,matrix.compose(position,q,scale));
        const tint=new THREE.Color(colors[kind]??0x8d9197);
        tint.multiplyScalar(.93+.07*((i*37)%11)/10);mesh.setColorAt(i,tint);
      }
      mesh.instanceMatrix.needsUpdate=true;mesh.userData.groundMatter=body.id;entry.group.add(mesh);
    }
    entry.full=!!body.cells?.length;
  }
  let enriching=false;
  async function enrich() {
    if(enriching)return;
    const wanted=[...bodies.values()].filter(entry=>!entry.full && !entry.requested);
    if(!wanted.length)return;
    enriching=true;wanted.forEach(entry=>entry.requested=true);
    const session=world.session;
    try {
      const answer=await api('/api/world/matter/shown',{session});
      if(world.session!==session)return;
      const packet=answer.ground_debris || answer;
      if(packet.schema!=='banjo.ground-debris.v1')return;
      for(const full of packet.bodies || []) {
        const entry=bodies.get(full.id);
        // A late metadata reply cannot resurrect a collected body or move a
        // current body backwards to the fetched packet's older pose.
        if(!entry || !full.cells?.length || entry.full)continue;
        entry.body={...full,...entry.body,cells:full.cells};buildGeometry(entry,entry.body);
      }
    } catch { /* Native slabs remain exact and visible without enrichment. */ }
    finally {
      enriching=false;
      if([...bodies.values()].some(entry=>!entry.full && !entry.requested))void enrich();
    }
  }
  function follow(packet) {
    if(!packet || packet.schema!=='banjo.ground-debris.v1')return;
    const seen=new Set();
    for(const body of packet.bodies || []) {
      // Native IDs survive snapshot/session rotation. A pre-collection tick
      // may arrive late, but its confirmed removed body cannot return.
      if(collected.has(body.id))continue;
      seen.add(body.id);
      let entry=bodies.get(body.id);
      if(!entry) {
        const group=new THREE.Group();group.name=`ground-matter-${body.id}`;
        group.userData.groundMatter=body.id;
        root.add(group);entry={group,body};bodies.set(body.id,entry);buildGeometry(entry,body);
      }
      else if(body.cells?.length && !entry.full)buildGeometry(entry,body);
      entry.body={...entry.body,...body,cells:body.cells || entry.body.cells};
      entry.group.position.fromArray(body.pose.center_m);
      const q=body.pose.orientation_wxyz;entry.group.quaternion.set(q[1],q[2],q[3],q[0]);
    }
    for(const [id,entry] of bodies)if(!seen.has(id)) {
      root.remove(entry.group);entry.group.traverse(mesh=>mesh.geometry?.dispose());bodies.delete(id);
    }
    void enrich();
  }
  function pick(from,dir,max=3) {
    ray.set(from,dir);ray.far=max;root.updateMatrixWorld(true);
    const hit=ray.intersectObjects(root.children,true)[0];
    if(!hit)return null;
    return {id:hit.object.userData.groundMatter,distance:hit.distance,point:hit.point};
  }
  async function collect(hit) {
    if(busy)return;
    busy=true;
    const id=hit.id,key=`banjo.matter-claim.${new URLSearchParams(location.search).get('world')}.${id}`;
    let request_id=localStorage.getItem(key);
    if(!request_id){request_id=crypto.randomUUID().replaceAll('-','');localStorage.setItem(key,request_id);}
    try {
      const answer=await api('/api/world/matter/collect',{session:world.session,id,request_id,person:whereIAm()});
      if(answer.ok!==true || !Array.isArray(answer.packet?.cells))
        throw Error('Collection has no confirmed material receipt. Retry the same block.');
      collected.add(id);
      if(answer.session)world.session=answer.session;
      if(answer.inventory){world.inventory=answer.inventory;showInventory?.();}
      // The authoritative receipt confirms that this exact body was removed.
      const entry=bodies.get(id);
      if(entry){root.remove(entry.group);entry.group.traverse(mesh=>mesh.geometry?.dispose());bodies.delete(id);}
      localStorage.removeItem(key);
      const packet=answer.packet;
      const names=[...new Set((packet.cells||[]).map(nameOf))].join(' + ');
      lastAction(`Collected ${names} · ${Number(packet.mass_kg).toFixed(1)} kg · Inventory`,'done');
    } finally {busy=false;}
  }
  return {follow,pick,collect,bodies};
}
