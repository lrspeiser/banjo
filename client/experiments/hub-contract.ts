export type Vec = [number, number, number];
export interface ContactNode { id:number; position_m:Vec; displacement_m:Vec; velocity_m_s:Vec; mass_kg:number; component:number; attached:boolean; clamped:boolean }
export interface Source { id:number; position_m:Vec; orientation_wxyz:[number,number,number,number]; velocity_m_s:Vec; angular_velocity_rad_s:Vec }
export interface ContactFrame { step:number; time_s:number; nodes:ContactNode[]; source:Source[]; bond_state:[boolean,number][]; components:number; broken_bonds:number; integration_error_j:number }
export interface ContactRun { material:string; width_m:number; dt_s:number; cell_m:number; density_kg_m3:number; young_modulus_pa:number; accepted_steps:number; attempted_steps:number; unsupported_region:string; bond_topology:[number,number][]; frames:ContactFrame[]; detached_mass_kg:number; contacts:number; attributed_linear_error_n_s:number; attributed_angular_error_kg_m2_s:number; attributed_energy_error_j:number }
export interface ContactRecording { schema:string; kind:string; open_convergence_gates:number; experiments:ContactRun[] }
export interface Check { id:string; name:string; kind:string; status?:string; exit_code?:number|null; elapsed_s?:number; output?:string; artifact_sha256?:string; recording_sha256?:string }
export interface Job { schema:string; id:string; selection:string; status:string; current:string; total:number; checks:Check[] }
const object=(v:unknown):Record<string,unknown>=>{if(!v||typeof v!=="object"||Array.isArray(v))throw Error("Expected object");return v as Record<string,unknown>;};
const number=(v:unknown,low=-1e100,high=1e100):number=>{if(typeof v!=="number"||!Number.isFinite(v)||v<low||v>high)throw Error("Invalid measurement");return v;};
const integer=(v:unknown,low:number,high:number):number=>{const n=number(v,low,high);if(!Number.isInteger(n))throw Error("Invalid identity/count");return n;};
const array=(v:unknown,min:number,max=min):unknown[]=>{if(!Array.isArray(v)||v.length<min||v.length>max)throw Error("Incomplete or oversized recording");return v;};
const vector=(v:unknown,length=3)=>array(v,length).forEach(x=>number(x));
const bool=(v:unknown)=>{if(typeof v!=="boolean")throw Error("Invalid state flag");};
export function validateContact(value:unknown):ContactRecording {
  const root=object(value);
  if(root.schema!=="banjo.contact-recording.v1"||root.kind!=="solver-recording")throw Error("Unknown contact recording");
  integer(root.open_convergence_gates,0,12);
  const identities=new Set<string>();
  for(const item of array(root.experiments,12)){
    const r=object(item);
    if(!["glass","oak","iron"].includes(String(r.material))||![.04,.12].includes(number(r.width_m))||![1e-7,5e-8].includes(number(r.dt_s))||r.cell_m!==.04)throw Error("Experiment conditions changed");
    const key=`${r.material}:${r.width_m}:${r.dt_s}`;if(identities.has(key))throw Error("Repeated experiment");identities.add(key);
    const count=r.dt_s===1e-7?2048:4096;const accepted=integer(r.accepted_steps,0,count);
    integer(r.attempted_steps,accepted,Math.min(count,accepted+1));
    if(typeof r.unsupported_region!=="string")throw Error("Missing admission result");
    const density=number(r.density_kg_m3,1,1e6);number(r.young_modulus_pa,1,1e15);number(r.detached_mass_kg,0,density*.001728+1e-10);integer(r.contacts,1,1e7);
    for(const field of ["attributed_linear_error_n_s","attributed_angular_error_kg_m2_s","attributed_energy_error_j"])number(r[field]);
    const topology=array(r.bond_topology,1,1000);
    const edges=new Set<string>();
    for(const pair of topology){const e=array(pair,2),a=integer(e[0],0,26),b=integer(e[1],0,26);const key=[a,b].sort((a,b)=>a-b).join(":");if(a===b||edges.has(key))throw Error("Invalid bond topology");edges.add(key);}
    const frames=array(r.frames,1,34);let previous=-1;
    for(const item of frames){
      const f=object(item);const step=integer(f.step,0,accepted);if(step<=previous||Math.abs(number(f.time_s)-step*number(r.dt_s))>1e-15)throw Error("Wrong physical clock");previous=step;
      integer(f.components,1,27);number(f.integration_error_j);
      let mass=0,clamps=0;
      for(const [i,item] of array(f.nodes,27).entries()){
        const n=object(item);if(n.id!==i)throw Error("Cell identity changed");vector(n.position_m);vector(n.displacement_m);vector(n.velocity_m_s);
        mass+=number(n.mass_kg,1e-12,1e6);integer(n.component,0,number(f.components)-1);bool(n.attached);bool(n.clamped);if(n.clamped){clamps++;if(!n.attached)throw Error("Detached clamp");}
      }
      if(clamps!==9||Math.abs(mass-density*.001728)>1e-9)throw Error("Mass/support mismatch");
      let broken=0;for(const state of array(f.bond_state,topology.length)){const s=array(state,2);bool(s[0]);number(s[1],0,1);if(!s[0])broken++;}
      if(f.broken_bonds!==broken)throw Error("Broken bond total mismatch");
      for(const [i,item] of array(f.source,2).entries()){
        const s=object(item);if(s.id!==[1,10][i])throw Error("Source identity changed");vector(s.position_m);vector(s.velocity_m_s);vector(s.angular_velocity_rad_s);vector(s.orientation_wxyz,4);
        const q=s.orientation_wxyz as number[];if(Math.abs(q.reduce((sum,v)=>sum+v*v,0)-1)>1e-5)throw Error("Invalid source orientation");
      }
    }
    if(object(frames[0]).step!==0||previous!==accepted||(accepted===count&&frames.length!==33))throw Error("Missing initial/final samples");
  }
  return value as ContactRecording;
}
export function validateJob(value:unknown,expected?:string):Job {
  const j=object(value);
  if(j.schema!=="banjo.test-job.v1"||typeof j.id!=="string"||!/^[0-9a-f]{32}$/.test(j.id)||(expected&&j.id!==expected)||!["running","completed"].includes(String(j.status)))throw Error("Wrong test execution");
  if(typeof j.current!=="string"||typeof j.selection!=="string")throw Error("Missing test selection");
  const total=integer(j.total,1,15),ids=new Set<string>();
  const checks=array(j.checks,0,total);
  for(const item of checks){const c=object(item);if(typeof c.id!=="string"||ids.has(c.id)||typeof c.name!=="string"||typeof c.kind!=="string"||typeof c.output!=="string"||c.output.length>30000)throw Error("Invalid check result");ids.add(c.id);
    if(!["pass","fail","error","unavailable"].includes(String(c.status)))throw Error("Unknown check status");
    if((c.status==="pass"&&c.exit_code!==0)||(c.status==="fail"&&(c.exit_code===0||c.exit_code===null)))throw Error("Exit status contradicts result");
    if(c.exit_code!==null)integer(c.exit_code,-2147483648,2147483647);number(c.elapsed_s,0,180);
    for(const field of ["artifact_sha256","recording_sha256"])if(c[field]!==undefined&&(typeof c[field]!=="string"||!/^[0-9a-f]{64}$/.test(String(c[field]))))throw Error("Invalid artifact fingerprint");
  }
  if(j.status==="completed"&&checks.length!==total)throw Error("Incomplete test job");
  return value as Job;
}
