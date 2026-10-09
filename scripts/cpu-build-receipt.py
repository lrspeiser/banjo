"""Record image build identity. This receipt proves identity, not physics validity."""
import argparse,hashlib,json,os
from pathlib import Path
from cpu_coupled_world import disk_source_hash,implementation_hash
p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True);p.add_argument('--native',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
os.environ['BANJO_COUPLED_CPU_LIBRARY']=str(a.library.resolve(strict=True))
revision=os.environ.get('RENDER_GIT_COMMIT') or None
if revision and (len(revision)!=40 or any(c not in '0123456789abcdef' for c in revision)):raise ValueError('Invalid build revision')
receipt=dict(schema='banjo.cpu-image-identity.v1',revision=revision,cpu_source_sha256=disk_source_hash(),cpu_implementation_sha256=implementation_hash(),native_sha256=hashlib.sha256(a.native.read_bytes()).hexdigest())
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
