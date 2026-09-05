"""Plot adjacent-timestep differences from compare-trajectories.py (requires matplotlib)."""
import argparse
import csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('comparison',type=Path)
parser.add_argument('--output',type=Path,required=True,help='Output stem; writes PNG and SVG')
args=parser.parse_args()
with args.comparison.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
colors={'glass':'#2563eb','oak':'#a16207','iron':'#0d9488'}
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(1,2,figsize=(11,5.8),sharey=True)
for ax,damping,title in zip(axes,('0','10000'),('Undamped interface','Compression damping: 10,000 kg/s')):
    for material,color in colors.items():
        group=sorted([r for r in rows if r['material']==material and r['damping_kg_s']==damping],
                     key=lambda r:-float(r['fine_dt_s']))
        if not group: raise ValueError(f'Missing comparison for {material}, damping={damping}')
        x=[float(r['fine_dt_s'])*1e6 for r in group]
        for column,style in (('sampled_max_velocity_rms_m_s','-'),('sampled_max_com_velocity_difference_m_s','--')):
            ax.plot(x,[float(r[column]) for r in group],style,color=color,marker='o',markersize=4,linewidth=1.8)
    ax.set_xscale('log',base=2); ax.set_yscale('log'); ax.invert_xaxis()
    ticks=sorted({float(r['fine_dt_s'])*1e6 for r in rows},reverse=True)
    ax.set_xticks(ticks,[f'{x:g}' for x in ticks])
    ax.set_xlabel('Finer timestep in each adjacent pair (microseconds)')
    ax.set_title(title,loc='left',fontsize=12,fontweight='bold')
    ax.grid(True,which='major',color='#cbd5e1',alpha=.7)
axes[0].set_ylabel('Largest sampled velocity difference (m/s)')
fig.suptitle('Bulk motion can hide unresolved internal motion',x=.07,y=.98,ha='left',fontsize=17,fontweight='bold')
fig.text(.07,.915,'Glass, oak and iron • identical geometry and interface parameters • 5 ms impacts',fontsize=10,color='#475569')
handles=[Line2D([0],[0],color=c,lw=2,label=m.capitalize()) for m,c in colors.items()]
handles += [Line2D([0],[0],color='#334155',lw=2,label='All-node mass-weighted RMS'),
            Line2D([0],[0],color='#334155',lw=2,ls='--',label='Center of mass')]
fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.07),ncol=3,frameon=False)
fig.text(.07,.025,'Differences compare neighboring rates at 51 shared times. They are not error bounds against an exact solution.',fontsize=9,color='#475569')
fig.subplots_adjust(left=.09,right=.98,bottom=.28,top=.82,wspace=.15)
args.output.parent.mkdir(parents=True,exist_ok=True)
for ext in ('.png','.svg'): fig.savefig(args.output.with_suffix(ext),dpi=180,facecolor='white')
print(f'Wrote {args.output.with_suffix(".png")} and SVG with matplotlib {matplotlib.__version__}')
