"""Conditional elastic native-material potentials, never accepted world motion.

Opening/compression choices retain shear, physical coefficients and all reaction
rows. Damage/yield crossings and rotation-log preload are not silently modeled.
"""
import math
import numpy as np


def attachment_hessian(row,axis,bodies):
    from coupled_modes import contact_gap_hessian
    # A rotating authored attachment axis is a moving plane. The B anchor is
    # its sample point; A's local-anchor projection is constant in this chart.
    r=np.zeros(34);r[:4]=[row[1],row[2],0,row[2]]
    r[6:9]=row[94:97];r[9:12]=row[97:100]+row[91:94];r[15]=0
    r[25:28]=row[82+3*axis:85+3*axis]
    return contact_gap_hessian(r,bodies)


def material_branch_model(evaluator,*,normal_at_zero):
    rows=evaluator.material_geometry();size=evaluator.n*6
    choices=[normal_at_zero]*len(rows) if isinstance(normal_at_zero,str) else list(normal_at_zero)
    if len(choices)!=len(rows) or any(choice not in ('opening','compression') for choice in choices):raise ValueError('Explicit material normal branch required for each attachment')
    stiffness=np.zeros((size,size));force=np.zeros(size);energy=0.;bounds=[];zero=0
    geometric_norm=0.;eps=np.finfo(float).eps
    for row,edge,choice in zip(rows,evaluator.edges,choices):
        a,b=int(row[1]),int(row[2]);kind=int(row[3]);q=row[4:10];j=row[10:82].reshape(6,12);s=edge[35:67]
        ids=np.r_[np.arange(a*6,a*6+6),np.arange(b*6,b*6+6)]
        scale=max(edge[3],np.linalg.norm(q[:3]),1e-30)
        tolerances=256*eps*np.r_[np.full(3,scale),np.full(3,max(np.linalg.norm(q[3:]),1.))]
        if kind!=0 and np.any(abs(q-s[22:28])>tolerances):raise ValueError('Material history does not match native geometry')
        if kind==0 and abs(q[0]-s[0])>tolerances[0]:raise ValueError('Normal history does not match native geometry')
        loads=np.zeros(6);diagonal=np.zeros(6)
        if kind in (0,2):
            k,strength,gc,area,compression=edge[18:23]
            effective=max(q[0],0.) if kind==0 else math.sqrt(max(q[0],0.)**2+edge[23]*np.dot(q[1:3],q[1:3]))
            onset=strength/k
            if 2*gc/strength<=onset:raise ValueError('Invalid cohesive softening interval')
            if s[5]!=0 or s[6]!=0 or max(effective,s[1])>=onset*(1-256*eps):raise ValueError('Cohesive damage/loading branch requires detailed continuation')
            history_coordinate=q[0] if kind==0 else effective
            if abs(s[0]-history_coordinate)>tolerances[0]*max(1.,math.sqrt(edge[23]) if kind==2 else 1.):raise ValueError('Cohesive effective history differs')
            if q[0]==0:zero+=1
            opening=q[0]>0 or (q[0]==0 and choice=='opening')
            diagonal[0]=area*(k if opening else compression if kind==0 else 0.)
            loads[0]=area*(k*max(q[0],0.)+compression*min(q[0],0.) if kind==0 else k*max(q[0],0.))
            if kind==2:diagonal[1:3]=area*k*edge[23];loads[1:3]=diagonal[1:3]*q[1:3]
            stored=.5*area*(k*effective**2+compression*min(q[0],0.)**2 if kind==0 else k*effective**2)
            uncertainty=128*eps*max(stored,abs(s[3]),1e-300)+np.linalg.norm(loads[:3])*np.linalg.norm(tolerances[:3])+.5*max(diagonal)*np.dot(tolerances[:3],tolerances[:3])
            if abs(stored-s[3])>uncertainty:raise ValueError('Cohesive stored history differs')
            bounds.append(dict(edge=int(row[0]),kind=kind,normal_coordinate_m=float(q[0]),effective_opening_m=effective,
                retained_maximum_opening_m=float(s[1]),damage_onset_m=onset,branch='opening' if opening else 'compression'))
        elif kind==1:
            diagonal=edge[23:29].copy();loads=diagonal*(q-s[:6]);yield_limit=edge[29:35]
            if np.any(abs(loads)>=yield_limit*(1-256*eps)):raise ValueError('Connector yield branch requires detailed continuation')
            if np.any(loads[3:]!=0):raise ValueError('Rotational preload needs qualified rotation-log curvature')
            stored=.5*np.dot(diagonal,(q-s[:6])**2)
            uncertainty=128*eps*max(stored,abs(s[15]),1e-300)+np.dot(abs(loads),tolerances)+.5*np.dot(diagonal,tolerances*tolerances)
            if abs(stored-s[15])>uncertainty:raise ValueError('Connector stored history differs')
            bounds.append(dict(edge=int(row[0]),kind=kind,yield_margin_n_nm=(yield_limit-abs(loads)).tolist(),branch='retained elastic rest'))
        else:raise ValueError('Unsupported material potential')
        # Sum the actual scalar-potential outer products in a fixed order.
        # This is symmetric by construction, without averaging independent
        # derivative columns or altering a nonsymmetric response afterward.
        local=np.zeros((12,12))
        for coefficient,gradient in zip(diagonal,j):local+=coefficient*np.outer(gradient,gradient)
        curvature=np.zeros((12,12))
        for axis in range(3):
            if loads[axis]!=0:curvature+=loads[axis]*attachment_hessian(row,axis,evaluator.bodies)
        local+=curvature;geometric_norm+=float(np.linalg.norm(curvature))
        stiffness[np.ix_(ids,ids)]+=local;force[ids]+=-j.T@loads;energy+=stored
    if not np.isfinite(stiffness).all() or not np.isfinite(force).all() or not math.isfinite(energy):raise ValueError('Nonfinite material potential')
    return dict(stiffness=stiffness,force=force,energy_j=energy,normal_at_zero=choices,
        zero_normal_edges=zero,elastic_limits=bounds,geometric_curvature_norm=geometric_norm,
        execution_admitted=False,scope='Conditional native elastic branch potential; nonlinear events and endpoint history still unqualified')
