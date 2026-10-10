"""Strict JSON-lines worker for the scalar native field laboratory."""
import json,sys
from thermal_fields import ThermalFields
world=None
for line in sys.stdin:
 try:
  if len(line)>100000:raise ValueError('Field request too large')
  cmd=json.loads(line)
  if not isinstance(cmd,dict):raise ValueError('Object command required')
  op=cmd.get('op')
  if op=='create' and set(cmd)=={'op','declaration'} and world is None:world=ThermalFields(cmd['declaration']);reply={'ok':True,'state':world.snapshot()}
  elif op=='restore' and set(cmd)=={'op','checkpoint'}:candidate=ThermalFields.restore(cmd['checkpoint']);world=candidate;reply={'ok':True,'state':world.snapshot()}
  elif op=='advance' and set(cmd)=={'op','steps'} and world:reply={'ok':True,'state':world.advance(cmd['steps'])}
  elif op=='snapshot' and set(cmd)=={'op'} and world:reply={'ok':True,'state':world.snapshot()}
  elif op=='export' and set(cmd)=={'op'} and world:reply={'ok':True,'checkpoint':world.export_checkpoint()}
  else:raise ValueError('Unsupported field command')
 except (ValueError,TypeError,KeyError,RuntimeError,OverflowError,MemoryError,OSError) as e:
  reply={'ok':False,'error':str(e)}
  if world:reply['state']=world.snapshot()
 print(json.dumps(reply,separators=(',',':'),allow_nan=False),flush=True)
